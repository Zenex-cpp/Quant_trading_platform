import pytest

from trading_platform.v37.user_stream_runtime import SessionState, UserStreamSessionCoordinator
from trading_platform.v39.binance_user_data_control import (
    BinanceUserDataControl,
    BinanceUserDataControlConfig,
    BinanceUserDataSessionManager,
    ControlResponseError,
    ControlTransportError,
    RuntimeCredential,
)


class FakeControlTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, *, url, payload, api_key):
        self.calls.append((url, dict(payload), api_key))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def ok(key):
    return {"status": 200, "result": {"listenKey": key}}


def empty_ok():
    return {"status": 200, "result": {}}


def test_control_start_is_tls_and_runtime_credential_only():
    t = FakeControlTransport([ok("lk")])
    control = BinanceUserDataControl(transport=t)
    assert control.start(RuntimeCredential("API")) == "lk"
    assert t.calls[0][0].startswith("wss://")
    assert t.calls[0][1]["method"] == "userDataStream.start"
    assert t.calls[0][1]["params"]["apiKey"] == "API"


def test_manager_start_enables_session_only_after_explicit_start_success():
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport([ok("lk")])
    manager = BinanceUserDataSessionManager(coordinator=c, control=BinanceUserDataControl(transport=t))
    snap = manager.start(credential=RuntimeCredential("API"), now_epoch=100.0)
    assert snap.state is SessionState.ACTIVE
    assert snap.control_healthy
    assert snap.listen_key == "lk"


def test_ping_failure_forces_expired_and_trading_off():
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport([ok("lk"), TimeoutError("timeout")])
    manager = BinanceUserDataSessionManager(coordinator=c, control=BinanceUserDataControl(transport=t))
    manager.start(credential=RuntimeCredential("API"), now_epoch=100.0)
    snap = manager.keepalive(credential=RuntimeCredential("API"), now_epoch=200.0)
    assert snap.state is SessionState.EXPIRED
    assert not snap.control_healthy
    assert not c.snapshot(200.0).trading_allowed


def test_ping_can_rotate_current_listen_key_without_enabling_extra_risk():
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport([ok("lk"), ok("lk2")])
    manager = BinanceUserDataSessionManager(coordinator=c, control=BinanceUserDataControl(transport=t))
    manager.start(credential=RuntimeCredential("API"), now_epoch=100.0)
    snap = manager.keepalive(credential=RuntimeCredential("API"), now_epoch=200.0)
    assert snap.listen_key == "lk2"
    assert snap.state is SessionState.ACTIVE
    assert snap.control_healthy


def test_stop_success_closes_session():
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport([ok("lk"), empty_ok()])
    manager = BinanceUserDataSessionManager(coordinator=c, control=BinanceUserDataControl(transport=t))
    manager.start(credential=RuntimeCredential("API"), now_epoch=100.0)
    snap = manager.stop(credential=RuntimeCredential("API"), now_epoch=150.0)
    assert snap.state is SessionState.CLOSED
    assert not snap.control_healthy
    assert t.calls[-1][1]["method"] == "userDataStream.stop"


def test_stop_uncertain_does_not_assume_success():
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport([ok("lk"), ControlTransportError("network")])
    manager = BinanceUserDataSessionManager(coordinator=c, control=BinanceUserDataControl(transport=t))
    manager.start(credential=RuntimeCredential("API"), now_epoch=100.0)
    snap = manager.stop(credential=RuntimeCredential("API"), now_epoch=150.0)
    assert snap.state is SessionState.EXPIRED
    assert not snap.control_healthy


def test_start_requires_real_api_key():
    t = FakeControlTransport([ok("lk")])
    control = BinanceUserDataControl(transport=t)
    with pytest.raises(PermissionError, match="RUNTIME_API_KEY_REQUIRED"):
        control.start(RuntimeCredential(""))


def test_config_rejects_non_tls_and_unsafe_interval():
    with pytest.raises(ValueError, match="TLS_CONTROL_WEBSOCKET_REQUIRED"):
        BinanceUserDataControlConfig(url="ws://bad").validate()
    with pytest.raises(ValueError, match="KEEPALIVE_INTERVAL_MUST_PRECEDE_EXPIRY"):
        BinanceUserDataControlConfig(keepalive_interval_s=3600).validate()


def test_non_200_is_explicit_control_error():
    t = FakeControlTransport([{"status":400,"result":{}}])
    control = BinanceUserDataControl(transport=t)
    with pytest.raises(ControlResponseError, match="STATUS_400"):
        control.start(RuntimeCredential("API"))

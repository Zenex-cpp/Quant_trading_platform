import pytest

from trading_platform.v37.user_stream_runtime import RecoveryAssessment, RecoveryCause, SessionState, UserStreamSessionCoordinator
from trading_platform.v38.websocket_runtime import BinanceUserStreamRuntime, SocketState, WebSocketConfig
from trading_platform.v39.binance_user_data_control import BinanceUserDataControl, BinanceUserDataControlConfig, RuntimeCredential
from trading_platform.v310.runtime_orchestrator import OrchestrationState, V310RuntimeOrchestrator


class FakeControlTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, *, url, payload, api_key):
        self.calls.append(dict(payload))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSocket:
    def __init__(self):
        self.connect_calls = []
        self.closed = False
        self.connected = False

    def connect(self, url):
        self.connect_calls.append(url)
        self.connected = True

    def send(self, payload):
        pass

    def recv(self, timeout_s):
        return None

    def close(self):
        self.closed = True
        self.connected = False


def ok(key):
    return {"status": 200, "result": {"listenKey": key}}


def empty_ok():
    return {"status": 200, "result": {}}


def build(responses, recovery=lambda cause: RecoveryAssessment(True, "OK", True, True, True)):
    c = UserStreamSessionCoordinator()
    t = FakeControlTransport(responses)
    control = BinanceUserDataControl(
        transport=t,
        config=BinanceUserDataControlConfig(keepalive_interval_s=100.0),
    )
    s = FakeSocket()
    ws = BinanceUserStreamRuntime(coordinator=c, transport=s, config=WebSocketConfig(url="wss://test"))
    o = V310RuntimeOrchestrator(coordinator=c, control=control, websocket=ws, recovery=recovery)
    return o, t, s


def test_complete_cycle_start_tick_disconnect_reconnect_recover():
    o, t, s = build([ok("lk1"), ok("lk1"), ok("lk2")])
    snap = o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    assert snap.trading_allowed
    snap = o.tick(credential=RuntimeCredential("API"), now_epoch=99.0)
    assert snap.state is OrchestrationState.ACTIVE
    snap = o.on_socket_disconnect(now_epoch=120.0)
    assert not snap.trading_allowed
    snap = o.recover(credential=RuntimeCredential("API"), now_epoch=121.0)
    assert snap.state is OrchestrationState.ACTIVE
    assert snap.trading_allowed
    assert s.connect_calls == ["wss://test", "wss://test"]
    assert [x["method"] for x in t.calls] == ["userDataStream.start", "userDataStream.start"]


def test_keepalive_scheduler_fires_once_and_reschedules():
    o, t, _ = build([ok("lk"), ok("lk")])
    o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    assert not o.tick(credential=RuntimeCredential("API"), now_epoch=99.9).keepalive_due
    snap = o.tick(credential=RuntimeCredential("API"), now_epoch=100.0)
    assert snap.last_action == "KEEPALIVE_OK"
    assert len(t.calls) == 2
    assert not o.snapshot(199.9).keepalive_due


def test_keepalive_failure_quarantines_socket_and_blocks_trading():
    o, _, s = build([ok("lk"), TimeoutError("timeout")])
    o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    snap = o.tick(credential=RuntimeCredential("API"), now_epoch=100.0)
    assert snap.state is OrchestrationState.KEEPALIVE_FAILED
    assert snap.session_state is SessionState.RECONNECTING
    assert snap.socket_state is SocketState.CLOSED
    assert not snap.trading_allowed
    assert snap.failure_count == 1


def test_expiry_then_controlled_reconnect_requires_recovery():
    o, t, _ = build([ok("lk"), ok("lk-new")])
    o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    o.on_listen_key_expiry(now_epoch=50.0)
    snap = o.tick(credential=RuntimeCredential("API"), now_epoch=51.0)
    assert snap.state is OrchestrationState.RECOVERING
    assert not snap.trading_allowed
    assert [x["method"] for x in t.calls] == ["userDataStream.start", "userDataStream.start"]

    snap = o.recover(credential=RuntimeCredential("API"), now_epoch=52.0)
    assert snap.trading_allowed


def test_recovery_failure_stays_blocked():
    def fail(_: RecoveryCause):
        return RecoveryAssessment(False, "REST_MISMATCH", True, False, True)

    o, _, _ = build([ok("lk"), ok("lk2")], recovery=fail)
    o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    o.on_socket_disconnect(now_epoch=10.0)
    snap = o.recover(credential=RuntimeCredential("API"), now_epoch=11.0)
    assert snap.state is OrchestrationState.BLOCKED
    assert not snap.trading_allowed
    assert snap.recovery_required


def test_control_start_failure_blocks_and_never_assumes_connection():
    o, _, s = build([TimeoutError("network")])
    snap = o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    assert snap.state is OrchestrationState.BLOCKED
    assert not snap.trading_allowed
    assert s.connect_calls == []


def test_stop_uncertain_quarantines():
    o, _, _ = build([ok("lk"), ConnectionError("network")])
    o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    snap = o.stop(credential=RuntimeCredential("API"), now_epoch=1.0)
    assert snap.state is OrchestrationState.BLOCKED
    assert not snap.trading_allowed


def test_idempotent_tick_when_not_due():
    o, t, _ = build([ok("lk")])
    a = o.start(credential=RuntimeCredential("API"), now_epoch=0.0)
    b = o.tick(credential=RuntimeCredential("API"), now_epoch=1.0)
    c = o.tick(credential=RuntimeCredential("API"), now_epoch=1.0)
    assert a.trading_allowed and b.trading_allowed and c.trading_allowed
    assert len(t.calls) == 1

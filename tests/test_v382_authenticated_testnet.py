from __future__ import annotations
import json
from decimal import Decimal

import pytest

from trading_platform.v382 import (
    AuthSessionState,
    AuthenticatedTestnetConfigV382,
    BinanceAuthenticatedTestnetSessionV382,
)
from trading_platform.v39.binance_user_data_control import BinanceUserDataControl, BinanceUserDataControlConfig


class FakeControlTransport:
    def __init__(self):
        self.calls = []
        self.next_key = "LK-1"
        self.ping_key = "LK-1"
        self.fail = False

    def request(self, *, url, payload, api_key):
        assert url == "wss://testnet.binancefuture.com/ws-fapi/v1"
        assert api_key == "APIKEY"
        self.calls.append(payload["method"])
        if self.fail:
            raise OSError("offline")
        if payload["method"] == "userDataStream.start":
            return {"id": payload["id"], "status": 200, "result": {"listenKey": self.next_key}}
        if payload["method"] == "userDataStream.ping":
            return {"id": payload["id"], "status": 200, "result": {"listenKey": self.ping_key}}
        if payload["method"] == "userDataStream.stop":
            return {"id": payload["id"], "status": 200, "result": {}}
        raise AssertionError(payload)


class FakeStream:
    def __init__(self, payloads=None):
        self.urls = []
        self.payloads = list(payloads or [])
        self.closed = False

    def connect(self, url):
        assert url.startswith("wss://stream.binancefuture.com/private/ws?")
        self.urls.append(url)
        self.closed = False

    def send(self, payload):
        raise AssertionError("SEND_NOT_EXPECTED")

    def recv(self, timeout_s):
        if not self.payloads:
            return None
        return self.payloads.pop(0)

    def close(self):
        self.closed = True


def _order_event(E=1000):
    return {"e":"ORDER_TRADE_UPDATE","E":E,"T":E,"o":{"s":"BTCUSDT","c":"cid","S":"BUY","o":"LIMIT","f":"GTC","q":"0.001","ap":"0","x":"NEW","X":"NEW","i":1,"l":"0","z":"0","L":"0","t":"0"}}


def _config():
    return AuthenticatedTestnetConfigV382(control_url="wss://testnet.binancefuture.com/ws-fapi/v1")


def _session(stream_payloads=None):
    ct = FakeControlTransport()
    control = BinanceUserDataControl(
        transport=ct,
        config=BinanceUserDataControlConfig(url="wss://testnet.binancefuture.com/ws-fapi/v1", keepalive_interval_s=3300),
        request_id=lambda: "RID",
    )
    stream = FakeStream(stream_payloads)
    s = BinanceAuthenticatedTestnetSessionV382(config=_config(), control=control, stream_transport=stream, clock=lambda: 1000.0)
    return s, ct, stream


def test_authenticated_session_start_connects_private_stream_and_blocks_nothing_local():
    s, ct, stream = _session([json.dumps(_order_event())])
    snap = s.start(api_key="APIKEY", now_epoch=1.0)
    assert snap.state is AuthSessionState.STREAMING
    assert snap.listen_key_present
    assert ct.calls == ["userDataStream.start"]
    assert len(stream.urls) == 1
    assert s.receive_once(now_epoch=1.001).accepted
    assert s.snapshot(1.001).stream_health.value == "HEALTHY"


def test_keepalive_key_rotation_reconnects_private_stream():
    s, ct, stream = _session()
    s.start(api_key="APIKEY", now_epoch=1.0)
    ct.ping_key = "LK-2"
    snap = s.keepalive(now_epoch=2.0)
    assert snap.state is AuthSessionState.STREAMING
    assert s.listen_key == "LK-2"
    assert len(stream.urls) == 2


def test_keepalive_failure_is_fail_closed():
    s, ct, stream = _session()
    s.start(api_key="APIKEY", now_epoch=1.0)
    ct.fail = True
    snap = s.keepalive(now_epoch=2.0)
    assert snap.state is AuthSessionState.DEGRADED
    assert not snap.trading_allowed


def test_listen_key_expiry_is_fail_closed():
    s, _, _ = _session([json.dumps({"e":"listenKeyExpired","E":1000,"T":1000})])
    s.start(api_key="APIKEY", now_epoch=1.0)
    r = s.receive_once(now_epoch=1.001)
    assert r is not None
    assert s.snapshot(1.001).state is AuthSessionState.EXPIRED
    assert not s.snapshot(1.001).trading_allowed


def test_production_control_url_is_rejected():
    with pytest.raises(PermissionError):
        AuthenticatedTestnetConfigV382(control_url="wss://ws-fapi.binance.com/ws-fapi/v1").validate()


def test_missing_control_url_is_not_verified_and_never_streams():
    ct = FakeControlTransport()
    control = BinanceUserDataControl(transport=ct, config=BinanceUserDataControlConfig(url="wss://testnet.binancefuture.com/ws-fapi/v1", keepalive_interval_s=3300), request_id=lambda: "RID")
    stream = FakeStream()
    s = BinanceAuthenticatedTestnetSessionV382(config=AuthenticatedTestnetConfigV382(control_url=""), control=control, stream_transport=stream, clock=lambda: 1.0)
    snap = s.start(api_key="APIKEY", now_epoch=1.0)
    assert snap.state is AuthSessionState.DEGRADED
    assert not snap.trading_allowed
    assert not ct.calls


def test_stop_drops_runtime_credentials_and_listen_key():
    s, ct, stream = _session()
    s.start(api_key="APIKEY", now_epoch=1.0)
    snap = s.stop(now_epoch=1001.0)
    assert snap.state is AuthSessionState.STOPPED
    assert not snap.listen_key_present
    assert ct.calls[-1] == "userDataStream.stop"
    assert stream.closed


def test_unknown_event_cannot_enable_trading():
    s, _, _ = _session([json.dumps({"e":"UNKNOWN_EVENT","E":1000,"T":1000})])
    s.start(api_key="APIKEY", now_epoch=1.0)
    r = s.receive_once(now_epoch=1.001)
    assert r is not None and not r.accepted
    assert not s.snapshot(1.001).trading_allowed

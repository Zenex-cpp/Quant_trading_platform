import pytest
from trading_platform.v19.user_stream import (
    KeepalivePolicy, StreamHealth, UserEventType, UserStreamMonitor,
    UserStreamSequencer, normalize_user_event,
)
from trading_platform.v19.reconciliation import UserStateReconciler


def event(t, T, status=None, et="ORDER_TRADE_UPDATE"):
    p={"e":et,"E":t,"T":T}
    if et == "ORDER_TRADE_UPDATE":
        p["o"]={"i":"123","s":"BTCUSDT","X":status or "NEW","x":"NEW"}
    return normalize_user_event(p)


def test_normalization_and_hash_are_deterministic():
    a=event(1000,900)
    b=event(1000,900)
    assert a.raw_hash == b.raw_hash
    assert a.order_id == "123" and a.symbol == "BTCUSDT"


def test_sequencer_rejects_out_of_order_events():
    s=UserStreamSequencer()
    assert s.accept(event(1000,900))
    assert not s.accept(event(999,899))
    assert s.health is StreamHealth.GAP_SUSPECTED


def test_expired_event_blocks():
    s=UserStreamSequencer()
    assert not s.accept(event(1000,900,et="listenKeyExpired"))
    assert s.health is StreamHealth.EXPIRED


def test_keepalive_policy_fails_closed():
    with pytest.raises(ValueError):
        KeepalivePolicy(keepalive_seconds=3600).validate()


def test_monitor_turns_stale_before_trading():
    m=UserStreamMonitor(KeepalivePolicy(stale_after_seconds=30, keepalive_seconds=300))
    m.started(1000, "LK")
    m.observe(event(1000000, 1000000))
    with pytest.raises(PermissionError, match="USER_STREAM_NOT_HEALTHY"):
        m.require_healthy_for_trading(1031)
    assert m.state(1031).health is StreamHealth.STALE


def test_reconciler_blocks_on_expiry_and_margin_call():
    r=UserStateReconciler()
    assert r.on_event(event(1000,900,et="listenKeyExpired")).blocking
    assert r.on_event(event(1000,900,et="MARGIN_CALL")).blocking


def test_reconciler_requires_terminal_order_reconcile():
    r=UserStateReconciler()
    out=r.on_event(event(1000,900,status="FILLED"))
    assert out.required and out.reason == "TERMINAL_ORDER_UPDATE"

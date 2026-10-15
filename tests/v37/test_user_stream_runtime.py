from pathlib import Path

from trading_platform.v37.user_stream_runtime import (
    DurableUserStreamStore,
    RecoveryAssessment,
    RecoveryCause,
    SessionState,
    UserStreamSessionCoordinator,
)


def payload(order_id=77, E=1000, T=999, client_id="cid-1", status="NEW", execution="NEW"):
    return {
        "e": "ORDER_TRADE_UPDATE", "E": E, "T": T,
        "o": {"s":"BTCUSDT", "c":client_id, "i":order_id, "x":execution, "X":status,
               "t":0, "l":"0", "L":"0", "z":"0", "n":"0", "N":"USDT", "T":E}
    }

def account_payload(E=1000, T=999, balance="1"):
    return {"e":"ACCOUNT_UPDATE", "E":E, "T":T, "a":{"B":[{"a":"USDT", "wb":balance}]}}


def test_sqlite_persists_duplicate_dedupe_across_restart(tmp_path: Path):
    db = str(tmp_path / "stream.db")
    s1 = DurableUserStreamStore(db)
    c1 = UserStreamSessionCoordinator(store=s1)
    c1.start(listen_key="lk", now_epoch=1.0)
    r1 = c1.observe(payload(), now_epoch=1.0)
    assert r1.accepted and not r1.duplicate
    s1.close()

    s2 = DurableUserStreamStore(db)
    c2 = UserStreamSessionCoordinator(store=s2)
    c2.start(listen_key="lk", now_epoch=2.0)
    r2 = c2.observe(payload(), now_epoch=2.0)
    assert r2.accepted and r2.duplicate and r2.reason == "PERSISTED_DUPLICATE"
    s2.close()


def test_disconnect_requires_recovery_before_trading():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    assert c.snapshot(1.0).trading_allowed
    c.disconnected(now_epoch=2.0)
    assert c.state is SessionState.RECONNECTING
    assert not c.snapshot(2.0).trading_allowed
    c.connected_after_reconnect(listen_key="lk2", now_epoch=3.0)
    assert c.state is SessionState.RECOVERING
    assert not c.snapshot(3.0).trading_allowed

    assessment = RecoveryAssessment(True, "OK", True, True, True)
    c.recover(assessment, now_epoch=3.1)
    assert c.state is SessionState.ACTIVE
    assert c.snapshot(3.1).trading_allowed


def test_failed_recovery_blocks():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    c.disconnected(now_epoch=2.0)
    c.connected_after_reconnect(listen_key="lk2", now_epoch=3.0)
    assessment = RecoveryAssessment(False, "POSITION_MISMATCH", True, False, True)
    c.recover(assessment, now_epoch=3.1)
    assert c.state is SessionState.BLOCKED
    assert not c.snapshot(3.1).trading_allowed


def test_listen_key_expiry_blocks_and_requires_new_stream():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    r = c.observe({"e":"listenKeyExpired","E":2000}, now_epoch=2.0)
    assert r.reason == "LISTEN_KEY_EXPIRED"
    assert c.state is SessionState.EXPIRED
    assert not c.snapshot(2.0).trading_allowed
    c.start(listen_key="lk2", now_epoch=3.0)
    assert c.state is SessionState.ACTIVE
    assert c.snapshot(3.0).trading_allowed


def test_out_of_order_same_event_type_enters_recovery():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    first = c.observe(account_payload(E=2000, T=1900), now_epoch=2.0)
    assert first.accepted
    second = c.observe(account_payload(E=1999, T=1899, balance="2"), now_epoch=2.1)
    assert second.reason == "ORDER_EVENT_OUT_OF_ORDER"
    assert c.state is SessionState.RECOVERING
    assert not c.snapshot(2.1).trading_allowed


def test_stale_stream_blocks_trading():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    c.observe(account_payload(E=1000, T=999), now_epoch=1.0)
    assert c.snapshot(100.0).stream_health.value == "STALE"
    assert not c.snapshot(100.0).trading_allowed


def test_recovery_callback_receives_precise_cause():
    c = UserStreamSessionCoordinator()
    c.start(listen_key="lk", now_epoch=1.0)
    c.disconnected(now_epoch=2.0)
    c.connected_after_reconnect(listen_key="lk2", now_epoch=3.0)
    seen = []
    def recover(cause):
        seen.append(cause)
        assert cause is RecoveryCause.DISCONNECT
        return RecoveryAssessment(True, "OK", True, True, True)
    c.recover_with(recover, now_epoch=4.0)
    assert seen == [RecoveryCause.DISCONNECT]


def test_recovery_blocks_when_durable_dispatch_attempt_is_unresolved(tmp_path):
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger
    from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger
    from trading_platform.v37.user_stream_runtime import RecoveryAssessment, UserStreamSessionCoordinator, SessionState
    attempts = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    attempts.prepare(intent_id="I", order_request_id="R", client_order_id="C",
                     request_fingerprint="RF", intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=10)
    recon = DurableDispatchReconciliationLedger(attempts.store, attempts=attempts)
    c = UserStreamSessionCoordinator(dispatch_reconciliation_ledger=recon)
    c.start(listen_key="LK", now_epoch=2.0)
    c.disconnected(now_epoch=3.0)
    r = c.recover(RecoveryAssessment(True, "OK", True, True, True), now_epoch=4.0)
    assert r.state is SessionState.BLOCKED
    assert r.recovery_required
    assert "RECOVERY_INCOMPLETE" in r.reason


def test_recovery_allows_ready_after_durable_dispatch_case_is_closed(tmp_path):
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptState
    from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger
    from trading_platform.v37.user_stream_runtime import RecoveryAssessment, UserStreamSessionCoordinator, SessionState
    attempts = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    attempts.prepare(intent_id="I", order_request_id="R", client_order_id="C",
                     request_fingerprint="RF", intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=10)
    recon = DurableDispatchReconciliationLedger(attempts.store, attempts=attempts)
    recon.reconcile(order_request_id="R", resolved_state=DispatchAttemptState.REJECTED,
                    evidence_id="4" * 64, evidence_source="REST_ORDER_STATUS",
                    evidence_fingerprint=DurableDispatchReconciliationLedger.evidence_fingerprint({"status":"REJECTED"}),
                    exchange_order_id=None, observed_at_ms=20)
    c = UserStreamSessionCoordinator(dispatch_reconciliation_ledger=recon)
    c.start(listen_key="LK", now_epoch=2.0)
    c.disconnected(now_epoch=3.0)
    r = c.recover(RecoveryAssessment(True, "OK", True, True, True), now_epoch=4.0)
    assert r.state is SessionState.ACTIVE
    assert not r.recovery_required

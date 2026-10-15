from __future__ import annotations

from pathlib import Path

import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v321.durable_dispatch import (
    DispatchAttemptConflict,
    DispatchAttemptState,
    DurableDispatchAttemptLedger,
)
from trading_platform.v322.durable_reconciliation import (
    DispatchReconciliationConflict,
    DispatchReconciliationReplayError,
    DurableDispatchReconciliationLedger,
)


RID = "R322"


def seed(tmp_path: Path, *, state: DispatchAttemptState = DispatchAttemptState.PENDING):
    store = EventStore(str(tmp_path / "attempt.db"))
    attempts = DurableDispatchAttemptLedger(store)
    attempts.prepare(
        intent_id="I322",
        order_request_id=RID,
        client_order_id="C322",
        request_fingerprint="RF322",
        intent_fingerprint="IF322",
        idempotency_key="K322",
        attempted_at_ms=100,
    )
    if state is DispatchAttemptState.UNKNOWN:
        attempts.observe(
            order_request_id=RID,
            state=DispatchAttemptState.UNKNOWN,
            exchange_order_id=None,
            outcome="UNKNOWN",
            reason="SUBMIT_EXCEPTION",
            observed_at_ms=110,
        )
    return store, attempts


def evidence_fp(status: str, exchange_order_id: str = "EX322") -> str:
    return DurableDispatchReconciliationLedger.evidence_fingerprint({
        "source": "TEST",
        "status": status,
        "client_order_id": "C322",
        "exchange_order_id": exchange_order_id,
        "event": "E322",
    })


def test_pending_can_be_closed_with_exact_evidence(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    rec = ledger.reconcile(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.ACKNOWLEDGED,
        evidence_id="a" * 64,
        evidence_source="USER_STREAM",
        evidence_fingerprint=evidence_fp("NEW"),
        exchange_order_id="EX322",
        observed_at_ms=200,
    )
    assert rec.resolved_state is DispatchAttemptState.ACKNOWLEDGED
    assert ledger.get(RID) == rec
    assert ledger.unresolved() == {}


def test_unknown_can_be_closed_by_rest_without_retry(tmp_path: Path):
    store, attempts = seed(tmp_path, state=DispatchAttemptState.UNKNOWN)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    ledger.reconcile(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.REJECTED,
        evidence_id="b" * 64,
        evidence_source="REST_ORDER_STATUS",
        evidence_fingerprint=evidence_fp("REJECTED", "EXREJ"),
        exchange_order_id="EXREJ",
        observed_at_ms=200,
    )
    assert ledger.unresolved() == {}
    with pytest.raises(DispatchAttemptConflict):
        attempts.prepare(
            intent_id="I322", order_request_id=RID, client_order_id="C322",
            request_fingerprint="RF322", intent_fingerprint="IF322",
            idempotency_key="K322", attempted_at_ms=201,
        )


def test_reconciliation_is_idempotent_only_for_same_evidence(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    kwargs = dict(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.CANCELLED,
        evidence_id="c" * 64,
        evidence_source="REST_ORDER_STATUS",
        evidence_fingerprint=evidence_fp("CANCELED", "EXC"),
        exchange_order_id="EXC",
        observed_at_ms=200,
    )
    first = ledger.reconcile(**kwargs)
    second = ledger.reconcile(**kwargs)
    assert first == second
    with pytest.raises(DispatchReconciliationConflict, match="RECONCILIATION_EVIDENCE_CONFLICT"):
        ledger.reconcile(**{**kwargs, "evidence_id": "d" * 64})


def test_wrong_binding_fails_closed(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    ledger.reconcile(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.ACKNOWLEDGED,
        evidence_id="e" * 64,
        evidence_source="USER_STREAM",
        evidence_fingerprint=evidence_fp("NEW"),
        exchange_order_id="EX1",
        observed_at_ms=200,
    )
    tamper_event_store(store,
        "UPDATE events SET payload_json=? WHERE event_id=?",
        ('{"order_request_id":"R322","intent_id":"OTHER","attempt_id":"dispatch:R322","client_order_id":"C322","resolved_state":"ACKNOWLEDGED","exchange_order_id":"EX1","evidence_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","evidence_source":"USER_STREAM","evidence_fingerprint":"%s","observed_at_ms":200}' % evidence_fp("NEW"),
 "dispatch:reconciled:R322"),)
    with pytest.raises(DispatchReconciliationReplayError, match="DISPATCH_RECONCILIATION_EVENT_CHAIN_INVALID"):
        ledger.restore()


def test_reconciliation_before_attempt_is_rejected(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    with pytest.raises(DispatchReconciliationConflict, match="RECONCILIATION_BEFORE_ATTEMPT_EVIDENCE"):
        ledger.reconcile(
            order_request_id=RID,
            resolved_state=DispatchAttemptState.ACKNOWLEDGED,
            evidence_id="f" * 64,
            evidence_source="USER_STREAM",
            evidence_fingerprint=evidence_fp("NEW"),
            exchange_order_id="EX322",
            observed_at_ms=99,
        )


def test_invalid_source_or_fingerprint_is_blocked(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    with pytest.raises(DispatchReconciliationConflict, match="RECONCILIATION_EVIDENCE_INVALID"):
        ledger.reconcile(
            order_request_id=RID,
            resolved_state=DispatchAttemptState.ACKNOWLEDGED,
            evidence_id="1" * 64,
            evidence_source="USER_STREAM",
            evidence_fingerprint="bad",
            exchange_order_id="EX322",
            observed_at_ms=200,
        )
    with pytest.raises(DispatchReconciliationConflict, match="INVALID_RECONCILIATION_SOURCE"):
        ledger.reconcile(
            order_request_id=RID,
            resolved_state=DispatchAttemptState.ACKNOWLEDGED,
            evidence_id="1" * 64,
            evidence_source="ARBITRARY",
            evidence_fingerprint=evidence_fp("NEW"),
            exchange_order_id="EX322",
            observed_at_ms=200,
        )


def test_restart_replay_preserves_closed_case(tmp_path: Path):
    store, attempts = seed(tmp_path, state=DispatchAttemptState.UNKNOWN)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    ledger.reconcile(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.ACKNOWLEDGED,
        evidence_id="2" * 64,
        evidence_source="REST_ORDER_STATUS",
        evidence_fingerprint=evidence_fp("FILLED"),
        exchange_order_id="EX322",
        observed_at_ms=200,
    )
    fresh = DurableDispatchReconciliationLedger(EventStore(str(tmp_path / "attempt.db")))
    assert fresh.restore()[RID].resolved_state is DispatchAttemptState.ACKNOWLEDGED
    fresh.assert_recovery_closed()


def test_unresolved_blocks_recovery_proof(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    assert RID in ledger.unresolved()
    with pytest.raises(DispatchReconciliationConflict, match="RECOVERY_INCOMPLETE"):
        ledger.assert_recovery_closed()


def test_no_raw_secret_or_transport_state_persisted(tmp_path: Path):
    store, attempts = seed(tmp_path)
    ledger = DurableDispatchReconciliationLedger(store, attempts=attempts)
    ledger.reconcile(
        order_request_id=RID,
        resolved_state=DispatchAttemptState.ACKNOWLEDGED,
        evidence_id="3" * 64,
        evidence_source="USER_STREAM",
        evidence_fingerprint=evidence_fp("NEW"),
        exchange_order_id="EX322",
        observed_at_ms=200,
    )
    raw = str(next(e for e in store.iter_events() if e.event_type == ledger.RECONCILED).payload).lower()
    assert "secret" not in raw
    assert "credential" not in raw
    assert "socket" not in raw
    assert "transport" not in raw
    assert "raw" not in raw

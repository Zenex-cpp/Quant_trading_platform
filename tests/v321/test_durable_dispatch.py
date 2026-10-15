from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, GuardedExecutionDispatcher
from trading_platform.v319 import DurableOrderIntentLedger
from trading_platform.v320 import DurableOrderRequestLedger
from trading_platform.v321 import (
    DispatchAttemptConflict,
    DispatchAttemptState,
    DurableDispatchAttemptLedger,
    DispatchAttemptReplayError,
)
from trading_platform.v33.commit import CommitCoordinator
from trading_platform.v34.execution_bridge import ExecutionBridge
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))


def truth():
    axes = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    return build_truth(
        observed_at_ns=1,
        axes=axes,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in (
            "health", "provenance", "governance", "reconciliation", "accounting", "ledger"
        )),
        requested_risk=Decimal("10"),
        caps={k: Decimal("10") for k in (
            "health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap"
        )},
    )


def intent():
    return OrderIntent(
        "I321D", "D321D", "P321D", "R321D", "S321D", "M321D", "E321D", "BTCUSDT",
        Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN, risk_reservation_id="RR321D",
    )


def runtime():
    return RuntimeCycleSnapshot(OrchestrationState.ACTIVE, "ACTIVE", "OPEN", True, True, False, False, "TEST", 0, "OK")


def committed_bridge(tmp_path: Path):
    i = intent(); t = truth()
    cap = CapabilityAuthority().issue(
        truth=t, requested_risk=Decimal("3"), decision_id=i.risk_decision_id,
        intent_payload=CommitCoordinator._payload(i), expires_at=NOW + timedelta(minutes=1),
    )
    intent_ledger = DurableOrderIntentLedger(EventStore(str(tmp_path / "intent.db")))
    request_ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "request.db")))
    b = ExecutionBridge(commit=CommitCoordinator(), order_intent_ledger=intent_ledger, order_request_ledger=request_ledger)
    b.commit_intent(
        capability=cap, intent=i, truth=t, now=NOW, position_state=PositionState.FLAT,
        market_window=WIN, upstream_windows=[WIN], risk_valid=True,
    )
    return b, i, request_ledger, intent_ledger


class Gateway:
    def __init__(self, result=None, error=None):
        self.calls = 0
        self.result = result or SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, f"cid:{intent().intent_id}", "EX321")
        self.error = error

    def submit(self, order, *, credentials):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def dispatcher(b, i, intent_ledger, request_ledger, attempt_ledger, gateway):
    return GuardedExecutionDispatcher(
        bridge=b,
        gateway=gateway,
        permission_snapshot=runtime,
        order_intent_ledger=intent_ledger,
        order_request_ledger=request_ledger,
        dispatch_attempt_ledger=attempt_ledger,
        clock_ms=lambda: int(NOW.timestamp() * 1000),
    )


def test_attempt_is_persisted_before_transport(tmp_path: Path):
    b, i, req_ledger, intent_ledger = committed_bridge(tmp_path)
    attempt_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    gateway = Gateway()
    seen = []

    class InspectingGateway(Gateway):
        def submit(self, order, *, credentials):
            rec = attempt_ledger.get(order.order_request_id)
            seen.append(rec.state if rec else None)
            return super().submit(order, credentials=credentials)

    d = dispatcher(b, i, intent_ledger, req_ledger, attempt_ledger, InspectingGateway())
    d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert seen == [DispatchAttemptState.PENDING]
    rec = attempt_ledger.get(b.committed_request(i.intent_id).request.order_request_id)
    assert rec is not None and rec.state is DispatchAttemptState.ACKNOWLEDGED


def test_pending_restart_blocks_second_transport(tmp_path: Path):
    b, i, req_ledger, intent_ledger = committed_bridge(tmp_path)
    req = b.committed_request(i.intent_id)
    fp_intent = DurableOrderIntentLedger.fingerprint(i)
    fp_req = DurableOrderRequestLedger.fingerprint(req, intent_fingerprint=fp_intent)
    store = EventStore(str(tmp_path / "attempt.db"))
    ledger = DurableDispatchAttemptLedger(store)
    ledger.prepare(
        intent_id=i.intent_id, order_request_id=req.request.order_request_id,
        client_order_id=req.request.client_order_id, request_fingerprint=fp_req,
        intent_fingerprint=fp_intent, idempotency_key=req.request.idempotency_key,
        attempted_at_ms=int(NOW.timestamp() * 1000),
    )
    fresh_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    gateway = Gateway()
    d = dispatcher(b, i, intent_ledger, req_ledger, fresh_ledger, gateway)
    with pytest.raises(DispatchGuardDenied, match="DISPATCH_ATTEMPT_PENDING_REQUIRES_RECONCILIATION"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == 0


def test_transport_exception_persists_unknown_and_blocks_retry(tmp_path: Path):
    b, i, req_ledger, intent_ledger = committed_bridge(tmp_path)
    attempt_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    gateway = Gateway(error=RuntimeError("timeout"))
    d = dispatcher(b, i, intent_ledger, req_ledger, attempt_ledger, gateway)
    with pytest.raises(RuntimeError, match="timeout"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    rid = b.committed_request(i.intent_id).request.order_request_id
    assert attempt_ledger.get(rid).state is DispatchAttemptState.UNKNOWN
    with pytest.raises(DispatchGuardDenied, match="SIDE_EFFECT_RETRY_BLOCKED:UNKNOWN"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == 1


def test_resolved_attempt_replays_durable_result_without_second_submit(tmp_path: Path):
    b, i, req_ledger, intent_ledger = committed_bridge(tmp_path)
    attempt_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    gateway = Gateway()
    d = dispatcher(b, i, intent_ledger, req_ledger, attempt_ledger, gateway)
    first = d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    second = d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == 1
    assert second.exchange_order_id == first.exchange_order_id
    assert second.exchange_outcome == first.exchange_outcome


def test_binding_conflict_fails_before_external_side_effect(tmp_path: Path):
    b, i, req_ledger, intent_ledger = committed_bridge(tmp_path)
    req = b.committed_request(i.intent_id)
    ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    fp_intent = DurableOrderIntentLedger.fingerprint(i)
    fp_req = DurableOrderRequestLedger.fingerprint(req, intent_fingerprint=fp_intent)
    ledger.prepare(
        intent_id=i.intent_id, order_request_id=req.request.order_request_id,
        client_order_id=req.request.client_order_id, request_fingerprint="tampered",
        intent_fingerprint=fp_intent, idempotency_key=req.request.idempotency_key,
        attempted_at_ms=int(NOW.timestamp() * 1000),
    )
    gateway = Gateway()
    d = dispatcher(b, i, intent_ledger, req_ledger, ledger, gateway)
    with pytest.raises(DispatchGuardDenied, match="DISPATCH_ATTEMPT_BINDING_CONFLICT"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == 0


def test_corrupt_attempt_event_chain_fails_closed(tmp_path: Path):
    store = EventStore(str(tmp_path / "attempt.db"))
    ledger = DurableDispatchAttemptLedger(store)
    ledger.prepare(
        intent_id="I", order_request_id="R", client_order_id="C", request_fingerprint="RF",
        intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=10,
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', 'dispatch:attempt:R'))
    with pytest.raises(DispatchAttemptReplayError, match="DISPATCH_ATTEMPT_EVENT_CHAIN_INVALID"):
        ledger.restore()


def test_second_prepare_cannot_claim_same_side_effect(tmp_path: Path):
    ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    first = ledger.prepare(
        intent_id="I", order_request_id="R", client_order_id="C", request_fingerprint="RF",
        intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=10,
    )
    assert first.state is DispatchAttemptState.PENDING
    with pytest.raises(DispatchAttemptConflict, match="DISPATCH_ATTEMPT_ALREADY_CLAIMED"):
        # The second prepare models a race where an earlier caller already claimed the
        # external side effect. It must never grant transport permission.
        ledger.prepare(
            intent_id="I", order_request_id="R", client_order_id="C", request_fingerprint="RF",
            intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=11,
        )


def test_attempt_evidence_contains_no_credentials_or_transport_objects(tmp_path: Path):
    ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    ledger.prepare(
        intent_id="I", order_request_id="R", client_order_id="C", request_fingerprint="RF",
        intent_fingerprint="IF", idempotency_key="K", attempted_at_ms=10,
    )
    raw = str(next(ledger.store.iter_events()).payload).lower()
    assert "secret" not in raw
    assert "credential" not in raw
    assert "socket" not in raw
    assert "transport" not in raw

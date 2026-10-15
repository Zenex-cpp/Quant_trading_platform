from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, GuardedExecutionDispatcher
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v33.commit import CommitCoordinator
from trading_platform.v34.execution_bridge import ExecutionBridge
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
from trading_platform.v319 import DurableOrderIntentLedger
from trading_platform.v320 import DurableOrderRequestLedger

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))


def truth():
    axes = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    return build_truth(
        observed_at_ns=1,
        axes=axes,
        components=tuple(
            TruthComponent(n, TruthStatus.VERIFIED, "OK")
            for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")
        ),
        requested_risk=Decimal("10"),
        caps={k: Decimal("10") for k in (
            "health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap"
        )},
    )


def intent():
    return OrderIntent(
        "I320D", "D320D", "P320D", "R320D", "S320D", "M320D", "E320D", "BTCUSDT",
        Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN, risk_reservation_id="RR320D",
    )


def runtime():
    return RuntimeCycleSnapshot(OrchestrationState.ACTIVE, "ACTIVE", "OPEN", True, True, False, False, "TEST", 0, "OK")


class Gateway:
    def __init__(self):
        self.calls = []

    def submit(self, order, *, credentials):
        self.calls.append(order)
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX320D")


def committed_bridge(tmp_path: Path, *, with_durable: bool):
    i = intent(); t = truth()
    cap_auth = CapabilityAuthority()
    cap = cap_auth.issue(
        truth=t, requested_risk=Decimal("3"), decision_id=i.risk_decision_id,
        intent_payload=CommitCoordinator._payload(i), expires_at=NOW + timedelta(minutes=1),
    )
    intent_ledger = DurableOrderIntentLedger(EventStore(str(tmp_path / "intent.db"))) if with_durable else None
    request_ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "request.db"))) if with_durable else None
    b = ExecutionBridge(
        commit=CommitCoordinator(),
        order_intent_ledger=intent_ledger,
        order_request_ledger=request_ledger,
    )
    b.commit_intent(
        capability=cap, intent=i, truth=t, now=NOW, position_state=PositionState.FLAT,
        market_window=WIN, upstream_windows=[WIN], risk_valid=True,
    )
    return b, i, t, request_ledger, intent_ledger


def test_bridge_commit_records_durable_request(tmp_path: Path):
    b, i, _, request_ledger, _ = committed_bridge(tmp_path, with_durable=True)
    assert request_ledger is not None
    rec = request_ledger.get(i.intent_id)
    assert rec is not None
    assert rec.request == b.committed_request(i.intent_id).request
    assert rec.request.client_order_id == f"cid:{i.intent_id}"


def test_final_dispatch_requires_durable_request(tmp_path: Path):
    b, i, t, _, intent_ledger = committed_bridge(tmp_path, with_durable=False)
    gateway = Gateway()
    request_ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "final-request.db")))
    guard = GuardedExecutionDispatcher(
        bridge=b, gateway=gateway, permission_snapshot=runtime,
        order_intent_ledger=intent_ledger, order_request_ledger=request_ledger,
        clock_ms=lambda: int(NOW.timestamp() * 1000),
    )
    with pytest.raises(DispatchGuardDenied, match="ORDER_REQUEST_DURABLE_DENIED:ORDER_REQUEST_NOT_FOUND"):
        guard.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == []


def test_final_dispatch_rejects_tampered_durable_request(tmp_path: Path):
    b, i, t, _, intent_ledger = committed_bridge(tmp_path, with_durable=False)
    gateway = Gateway()
    request_ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "final-request.db")))
    req = b.committed_request(i.intent_id)
    tampered = replace(req, request=replace(req.request, quantity=Decimal("0.002")))
    fp = DurableOrderIntentLedger.fingerprint(i)
    request_ledger.record(tampered, intent_fingerprint=fp, recorded_at_ms=int(NOW.timestamp() * 1000))
    guard = GuardedExecutionDispatcher(
        bridge=b, gateway=gateway, permission_snapshot=runtime,
        order_intent_ledger=intent_ledger, order_request_ledger=request_ledger,
        clock_ms=lambda: int(NOW.timestamp() * 1000),
    )
    with pytest.raises(DispatchGuardDenied, match="ORDER_REQUEST_DURABLE_DENIED:ORDER_REQUEST_PAYLOAD_MISMATCH"):
        guard.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert gateway.calls == []


def test_final_dispatch_accepts_exact_durable_request(tmp_path: Path):
    b, i, _, request_ledger, _ = committed_bridge(tmp_path, with_durable=True)
    gateway = Gateway()
    assert request_ledger is not None
    guard = GuardedExecutionDispatcher(
        bridge=b, gateway=gateway, permission_snapshot=runtime,
        order_request_ledger=request_ledger,
        clock_ms=lambda: int(NOW.timestamp() * 1000),
    )
    receipt = guard.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert receipt.exchange_order_id == "EX320D"
    assert len(gateway.calls) == 1

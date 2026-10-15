from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v315 import DurableAccountingLedger, DurableFill
from trading_platform.v316 import DurableAccountingAuthority
from trading_platform.v317 import DurableRiskReservationBook, RiskReservationGate, RiskReservationRecord, RiskReservationState
from trading_platform.risk.budget import BudgetScope
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, GuardedExecutionDispatcher
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth():
    return build_truth(
        observed_at_ns=1,
        axes=AX,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")),
        requested_risk=Decimal("100"),
        caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")},
    )


def payload():
    return {"intent_id":"I317","decision_id":"D317","risk_decision_id":"R317","portfolio_decision_id":"P317","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E317"}


def build_pair():
    cc = __import__("trading_platform.v33.commit", fromlist=["CommitCoordinator"]).CommitCoordinator()
    t = truth()
    cap = cc.capabilities.issue(truth=t, requested_risk=Decimal("3"), decision_id="D317", intent_payload=payload(), expires_at=NOW + timedelta(seconds=30))
    i = OrderIntent("I317", "D317", "P317", "R317", "S317", "M317", "E317", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN, risk_reservation_id="rr317")
    b = ExecutionBridge(commit=cc)
    obs = b.commit_intent(capability=cap, intent=i, truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert obs.status is BridgeStatus.COMMITTED
    return b, i


def snap():
    return RuntimeCycleSnapshot(OrchestrationState.ACTIVE, "ACTIVE", "OPEN", True, True, False, False, "TEST", 0, "OK")


class FakeGateway:
    def __init__(self):
        self.calls = []
    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX317")


def accounting(tmp_path: Path):
    authority = DurableAccountingAuthority(
        DurableAccountingLedger(EventStore(str(tmp_path / "acct.db")))
    )
    authority.ledger.append_fill(DurableFill("af317", "ao317", "BTCUSDT", "BUY", Decimal("1"), Decimal("100")))
    authority.restore()
    authority.mark_reconciled(evidence_id="recon317")
    return authority


def reservation(tmp_path: Path, accounting_hash: str):
    book = DurableRiskReservationBook(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    book.reserve(RiskReservationRecord("rr317", BudgetScope.ORDER, Decimal("3"), Decimal("3"), "I317", "R317", accounting_hash, 100, 200000))
    return RiskReservationGate(book), book


def test_missing_reservation_blocks_before_transport(tmp_path: Path):
    b, i = build_pair()
    g = FakeGateway()
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=snap, accounting_authority=accounting(tmp_path), risk_reservation_gate=RiskReservationGate(book=DurableRiskReservationBook(EventStore(str(tmp_path / "unused.db")), allocated=Decimal("10"))))
    with pytest.raises(DispatchGuardDenied, match="RISK_RESERVATION_DENIED:RESERVATION_NOT_FOUND"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert g.calls == []


def test_valid_reservation_is_consumed_before_transport(tmp_path: Path):
    b, i = build_pair()
    acct = accounting(tmp_path)
    gate, book = reservation(tmp_path, acct.snapshot().projection_hash)
    g = FakeGateway()
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=snap, accounting_authority=acct, risk_reservation_gate=gate, clock_ms=lambda: 101)
    d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert len(g.calls) == 1
    assert book.reservations()[0].state is RiskReservationState.CONSUMED


def test_stale_accounting_binding_blocks_and_makes_no_transport(tmp_path: Path):
    b, i = build_pair()
    acct = accounting(tmp_path)
    gate, book = reservation(tmp_path, "different-hash")
    g = FakeGateway()
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=snap, accounting_authority=acct, risk_reservation_gate=gate, clock_ms=lambda: 101)
    with pytest.raises(DispatchGuardDenied, match="RISK_RESERVATION_DENIED:RESERVATION_ACCOUNTING_HASH_STALE"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert g.calls == []
    assert book.reservations()[0].state is RiskReservationState.RESERVED


def test_consumed_reservation_does_not_double_consume_on_retry(tmp_path: Path):
    b, i = build_pair()
    acct = accounting(tmp_path)
    gate, book = reservation(tmp_path, acct.snapshot().projection_hash)
    g = FakeGateway()
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=snap, accounting_authority=acct, risk_reservation_gate=gate, clock_ms=lambda: 101)
    first = d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    second = d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert len(g.calls) == 1
    assert second.exchange_order_id == first.exchange_order_id
    assert book.projection.consumed == Decimal("3")


class AmbiguousGateway(FakeGateway):
    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        raise RuntimeError("TRANSPORT_AMBIGUOUS")


def test_transport_ambiguity_leaves_reservation_consumed(tmp_path: Path):
    b, i = build_pair()
    acct = accounting(tmp_path)
    gate, book = reservation(tmp_path, acct.snapshot().projection_hash)
    g = AmbiguousGateway()
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=snap, accounting_authority=acct, risk_reservation_gate=gate, clock_ms=lambda: 101)
    with pytest.raises(RuntimeError, match="TRANSPORT_AMBIGUOUS"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert len(g.calls) == 1
    assert book.reservations()[0].state is RiskReservationState.CONSUMED

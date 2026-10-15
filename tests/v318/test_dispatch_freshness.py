from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v33.commit import CommitCoordinator
from trading_platform.v34.execution_bridge import ExecutionBridge
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
from trading_platform.v315 import DurableAccountingLedger, DurableFill
from trading_platform.v316 import DurableAccountingAuthority
from trading_platform.v317.durable_risk import DurableRiskReservationBook, RiskReservationGate, RiskReservationRecord
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionRecord, RiskSystemState
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, GuardedExecutionDispatcher
from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)
BASE_MS = int(NOW.timestamp() * 1000)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth():
    return build_truth(observed_at_ns=1, axes=AX,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
        requested_risk=Decimal("100"), caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})


def payload():
    return {"intent_id":"I318","decision_id":"D318","risk_decision_id":"R318","portfolio_decision_id":"P318","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E318"}


def build_bridge():
    cc = CommitCoordinator(); t = truth()
    cap = cc.capabilities.issue(truth=t, requested_risk=Decimal("3"), decision_id="D318", intent_payload=payload(), expires_at=NOW + timedelta(seconds=30))
    i = OrderIntent("I318","D318","P318","R318","S318","M318","E318","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WIN,risk_reservation_id="RR318")
    b = ExecutionBridge(commit=cc)
    b.commit_intent(capability=cap, intent=i, truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    return b, i, t


def runtime():
    return RuntimeCycleSnapshot(OrchestrationState.ACTIVE,"ACTIVE","OPEN",True,True,False,False,"TEST",0,"OK")


class G:
    def __init__(self): self.calls=[]
    def submit(self, order, *, credentials):
        self.calls.append(order)
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX318")


def risk(ledger_path: str, truth_hash: str):
    ledger = DurableRiskDecisionLedger(EventStore(ledger_path))
    ledger.record(RiskDecisionRecord(
        decision_id="R318", action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("3"), allowed_exposure=Decimal("3"), active_limits={"order":Decimal("3")},
        multipliers={"uncertainty":Decimal("1")}, rejection_reason=None, reservation_id="RR318", intent_id="I318",
        created_at_ms=BASE_MS, valid_from_ms=BASE_MS, expires_at_ms=BASE_MS + 100000, configuration_version="cfg1", risk_state_version="rs1",
        portfolio_version="pv1", position_version="pos1", provenance_id="prov1", truth_hash=truth_hash, input_fingerprint="fp1"))
    return ledger


def accounting(path: str):
    authority = DurableAccountingAuthority(DurableAccountingLedger(EventStore(path)))
    authority.ledger.append_fill(DurableFill("af318", "ao318", "BTCUSDT", "BUY", Decimal("1"), Decimal("100")))
    authority.restore()
    authority.mark_reconciled(evidence_id="recon318")
    return authority


def reservation(path: str, truth_hash: str):
    b=DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    b.reserve(RiskReservationRecord("RR318", __import__("trading_platform.risk.budget", fromlist=["BudgetScope"]).BudgetScope.ORDER, Decimal("3"), Decimal("3"), "I318", "R318", truth_hash, BASE_MS, BASE_MS + 100000))
    return RiskReservationGate(b)


def test_expired_risk_decision_blocks_before_transport(tmp_path: Path):
    b,i,t=build_bridge(); g=G()
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash), clock_ms=lambda: BASE_MS + 100000)
    with pytest.raises(DispatchGuardDenied, match="RISK_DECISION_DENIED:RISK_DECISION_EXPIRED_OR_NOT_YET_VALID"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_valid_risk_decision_and_reservation_dispatch(tmp_path: Path):
    b,i,t=build_bridge(); g=G()
    acct=accounting(str(tmp_path/"acct.db"))
    gate=reservation(str(tmp_path/"riskr.db"), acct.snapshot().projection_hash)
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime, accounting_authority=acct,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash),
        risk_reservation_gate=gate, clock_ms=lambda: BASE_MS + 50000)
    r=d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert r.exchange_order_id == "EX318"
    assert len(g.calls)==1


def test_order_intent_window_and_request_deadline_are_final_guards(tmp_path: Path):
    b,i,t=build_bridge(); g=G()
    expired = OrderIntent(i.intent_id,i.decision_id,i.portfolio_decision_id,i.risk_decision_id,i.strategy_id,i.model_id,i.execution_version,i.symbol,i.side,i.action,i.quantity,i.order_type,ValidWindow(NOW-timedelta(minutes=5),NOW-timedelta(seconds=1)),risk_reservation_id=i.risk_reservation_id)
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash),
        risk_reservation_gate=reservation(str(tmp_path/"riskr.db"), t.state_hash), clock_ms=lambda: BASE_MS + 50000)
    with pytest.raises(DispatchGuardDenied, match="ORDER_INTENT_NOT_FRESH"):
        d.dispatch_submit(intent=expired, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_order_request_deadline_blocks_before_transport(tmp_path: Path):
    b,i,t=build_bridge(); g=G()
    req = b._requests[i.intent_id]
    b._requests[i.intent_id] = replace(req, request=replace(req.request, deadline=NOW - timedelta(seconds=1)))
    acct=accounting(str(tmp_path/"acct.db"))
    gate=reservation(str(tmp_path/"riskr.db"), acct.snapshot().projection_hash)
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime, accounting_authority=acct,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash),
        risk_reservation_gate=gate, clock_ms=lambda: BASE_MS + 50000)
    with pytest.raises(DispatchGuardDenied, match="ORDER_REQUEST_EXPIRED"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_committed_intent_identity_is_final_guard(tmp_path: Path):
    b,i,t=build_bridge(); g=G()
    tampered = replace(i, quantity=Decimal("0.002"))
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash), clock_ms=lambda: BASE_MS + 50000)
    with pytest.raises(DispatchGuardDenied, match="COMMITTED_INTENT_MISMATCH"):
        d.dispatch_submit(intent=tampered, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_durable_order_intent_missing_or_tampered_blocks_before_transport(tmp_path: Path):
    from trading_platform.v319 import DurableOrderIntentLedger
    b,i,t=build_bridge(); g=G()
    ledger=DurableOrderIntentLedger(EventStore(str(tmp_path/"intent.db")))
    d=GuardedExecutionDispatcher(bridge=b,gateway=g,permission_snapshot=runtime,
        risk_decision_ledger=risk(str(tmp_path/"riskd.db"), t.state_hash),
        order_intent_ledger=ledger, clock_ms=lambda: BASE_MS + 50000)
    with pytest.raises(DispatchGuardDenied, match="ORDER_INTENT_DURABLE_DENIED:ORDER_INTENT_NOT_FOUND"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    ledger.record(replace(i, quantity=Decimal("0.002")), recorded_at_ms=BASE_MS)
    with pytest.raises(DispatchGuardDenied, match="ORDER_INTENT_DURABLE_DENIED:ORDER_INTENT_PAYLOAD_MISMATCH"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls

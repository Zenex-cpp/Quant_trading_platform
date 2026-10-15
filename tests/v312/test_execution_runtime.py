from datetime import datetime, timezone, timedelta
from decimal import Decimal

from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v33.commit import CommitCoordinator
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation, ExchangeUncertain
from trading_platform.v310.runtime_orchestrator import RuntimeCycleSnapshot, OrchestrationState
from trading_platform.v312.execution_runtime import ExecutionRuntimeIntegration
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v331 import PositionAuthorityLedger
from trading_platform.v332 import MarketDataAuthorityLedger
from trading_platform.v333 import CausalTTLAuthorityLedger
from tests.causal_helpers import causal_authority_for_intent
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
BASE_MS = int(NOW.timestamp() * 1000)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth():
    return build_truth(observed_at_ns=1, axes=AX,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
        requested_risk=Decimal("100"), caps={k: Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})


def intent():
    return OrderIntent("I312","D312","P312","R312","S312","M312","E312","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WIN)



def position_authority():
    ledger = PositionAuthorityLedger()
    recon = ReconciliationResult(
        ReconciliationState.GREEN, ReconciliationDiff(),
        "rest-hash", "stream-hash", "REST_WS_MATCH",
    )
    ledger.record_reconciliation(
        symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"),
        reconciliation=recon, observed_at_ms=BASE_MS, ttl_ms=10_000,
        position_state=PositionState.FLAT,
    )
    return ledger


def market_authority():
    ledger = MarketDataAuthorityLedger()
    ledger.record_observation(
        symbol="BTCUSDT", feed_id="primary", event_time_ms=BASE_MS, receive_time_ms=BASE_MS,
        processing_time_ms=BASE_MS, max_age_ms=10000, source="test", sequence_number=1,
    )
    return ledger

def payload():
    return {"intent_id":"I312","decision_id":"D312","risk_decision_id":"R312","portfolio_decision_id":"P312","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E312"}


def bridge():
    cc = CommitCoordinator()
    t = truth()
    cap = cc.capabilities.issue(truth=t, requested_risk=Decimal("10"), decision_id="D312", intent_payload=payload(), expires_at=NOW + timedelta(seconds=30))
    b = ExecutionBridge(commit=cc)
    obs = b.commit_intent(capability=cap, intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert obs.status is BridgeStatus.COMMITTED
    return b


class FakeGateway:
    def __init__(self, behavior): self.behavior, self.calls = behavior, []
    def submit(self, order, *, credentials):
        self.calls.append(order)
        return self.behavior(order, credentials)


class FakeOrchestrator:
    def __init__(self):
        self.allowed = True
    def snapshot(self, now):
        return RuntimeCycleSnapshot(OrchestrationState.ACTIVE if self.allowed else OrchestrationState.BLOCKED, "ACTIVE", "OPEN", True, self.allowed, False, not self.allowed, "TEST", 0, "OK" if self.allowed else "BLOCKED")


def test_true_path_uses_committed_bridge_request_and_testnet_gateway():
    b = bridge(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX312"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()))
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp())
    assert res.submitted is True and res.exchange_uncertain is False
    assert res.receipt is not None and res.receipt.exchange_order_id == "EX312"
    assert len(g.calls) == 1


def test_transport_uncertainty_marks_unknown_and_requires_reconciliation():
    b = bridge(); o = FakeOrchestrator()
    def uncertain(order, credentials): raise ExchangeUncertain("SUBMIT_OUTCOME_UNKNOWN")
    g = FakeGateway(uncertain)
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()))
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp())
    assert res.exchange_uncertain is True and res.recovery_required is True
    assert b._lifecycles[intent().intent_id].state.value == "UNKNOWN"


def test_permission_lost_after_network_dispatch_is_not_reported_as_clean_cycle():
    b = bridge(); o = FakeOrchestrator()
    def behavior(order, credentials):
        o.allowed = False
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX312-RACE")
    g = FakeGateway(behavior)
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()))
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp())
    assert res.submitted is True
    assert res.recovery_required is True
    assert res.reason == "PERMISSION_LOST_DURING_CYCLE"


def test_blocked_runtime_makes_zero_exchange_calls():
    b = bridge(); o = FakeOrchestrator(); o.allowed = False
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "NEVER"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()))
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp())
    assert not res.submitted and not g.calls


def test_missing_causal_ttl_authority_blocks_before_gateway():
    b = bridge(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "NEVER"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority())
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp())
    assert res.submitted is False
    assert "CAUSAL_TTL_DENIED:CAUSAL_TTL_INTENT_NOT_FOUND" in res.reason
    assert g.calls == []

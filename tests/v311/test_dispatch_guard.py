from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, GuardedExecutionDispatcher
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
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


def intent():
    return OrderIntent("I311", "D311", "P311", "R311", "S311", "M311", "E311", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN)


def payload():
    return {"intent_id":"I311","decision_id":"D311","risk_decision_id":"R311","portfolio_decision_id":"P311","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E311"}


def valid_bridge():
    cc = __import__("trading_platform.v33.commit", fromlist=["CommitCoordinator"]).CommitCoordinator()
    t = truth()
    cap = cc.capabilities.issue(truth=t, requested_risk=Decimal("10"), decision_id="D311", intent_payload=payload(), expires_at=NOW + timedelta(seconds=30))
    b = ExecutionBridge(commit=cc)
    obs = b.commit_intent(capability=cap, intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert obs.status is BridgeStatus.COMMITTED
    return b, intent()


def snap(allowed: bool, reason="OK"):
    return RuntimeCycleSnapshot(OrchestrationState.ACTIVE if allowed else OrchestrationState.BLOCKED, "ACTIVE", "OPEN", True, allowed, False, False, "TEST", 0, reason)


class FakeGateway:
    def __init__(self, obs):
        self.obs = obs
        self.calls = []
    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        return self.obs


def test_denied_runtime_blocks_before_transport():
    b, i = valid_bridge()
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, "cid", "ex"))
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=lambda: snap(False, "RECOVERY"))
    with pytest.raises(DispatchGuardDenied, match="TRADING_NOT_ALLOWED"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert g.calls == []


def test_allowed_runtime_dispatches_exact_committed_request():
    b, i = valid_bridge()
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, b._requests[i.intent_id].request.client_order_id, "EX123"))
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=lambda: snap(True))
    receipt = d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert len(g.calls) == 1
    assert g.calls[0][0] == b._requests[i.intent_id].request
    assert receipt.exchange_order_id == "EX123"
    assert receipt.bridge_status is BridgeStatus.OBSERVED


def test_recovery_required_blocks_even_if_state_flag_is_inconsistent():
    b, i = valid_bridge()
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, "cid", "ex"))
    bad = RuntimeCycleSnapshot(OrchestrationState.ACTIVE, "ACTIVE", "OPEN", True, True, False, True, "RECOVERY", 0, "GAP")
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=lambda: bad)
    with pytest.raises(DispatchGuardDenied, match="RECOVERY_REQUIRED"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_unknown_local_lifecycle_blocks_dispatch():
    b, i = valid_bridge()
    b.mark_unknown(i.intent_id, exchange_order_id="EX", client_order_id=b._requests[i.intent_id].request.client_order_id)
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, "cid", "ex"))
    d = GuardedExecutionDispatcher(bridge=b, gateway=g, permission_snapshot=lambda: snap(True))
    with pytest.raises(ValueError, match="UNKNOWN_ORDER_NO_BLIND_RETRY"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert not g.calls


def test_accounting_unknown_blocks_before_transport():
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v315 import DurableAccountingLedger, DurableFill
    from trading_platform.v316 import DurableAccountingAuthority

    ledger = DurableAccountingLedger(EventStore())
    ledger.append_fill(DurableFill("af1", "ao1", "BTCUSDT", "BUY", Decimal("1"), Decimal("100")))
    authority = DurableAccountingAuthority(ledger)
    authority.restore()
    b, i = valid_bridge()
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, "cid", "ex"))
    d = GuardedExecutionDispatcher(
        bridge=b,
        gateway=g,
        permission_snapshot=lambda: snap(True),
        accounting_authority=authority,
    )
    with pytest.raises(DispatchGuardDenied, match="ACCOUNTING_NOT_ALLOWED:UNRECONCILED:"):
        d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert g.calls == []


def test_reconciled_accounting_allows_transport():
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v315 import DurableAccountingLedger, DurableFill
    from trading_platform.v316 import DurableAccountingAuthority

    ledger = DurableAccountingLedger(EventStore())
    ledger.append_fill(DurableFill("af2", "ao2", "BTCUSDT", "BUY", Decimal("1"), Decimal("100")))
    authority = DurableAccountingAuthority(ledger)
    authority.restore()
    authority.mark_reconciled(evidence_id="recon-1")
    b, i = valid_bridge()
    g = FakeGateway(SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, b._requests[i.intent_id].request.client_order_id, "EX-A"))
    d = GuardedExecutionDispatcher(
        bridge=b,
        gateway=g,
        permission_snapshot=lambda: snap(True),
        accounting_authority=authority,
    )
    d.dispatch_submit(intent=i, credentials=RuntimeCredentialValues("API", b"SECRET"))
    assert len(g.calls) == 1

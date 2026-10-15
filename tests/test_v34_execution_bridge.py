from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderIntent, Side, OrderAction, OrderType, PositionState, Fill
from trading_platform.v30.truth import OperationalTruth, AxisSnapshot, TruthComponent, TruthStatus, RiskEnvelope
from trading_platform.v31.authority import RuntimeAuthority
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus


def now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def truth():
    components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "test", ("e1",)) for name in (
        "health", "provenance", "governance", "reconciliation", "accounting", "ledger"
    ))
    return OperationalTruth(
        observed_at_ns=int(now().timestamp() * 1_000_000_000),
        axes=AxisSnapshot("ACTIVE", "CANARY", "HEALTHY", "APPROVED", "CANARY", "TRADER"),
        components=components,
        risk=RiskEnvelope(Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10")),
        decision_fresh=True,
    )


def intent():
    n = now()
    return OrderIntent("i1", "d1", "p1", "r1", "s1", "m1", "ex1", "BTCUSDT", Side.BUY,
                       OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET,
                       ValidWindow(n, n + timedelta(minutes=5)))


def capability():
    t = truth(); i = intent(); payload = {"intent_id": i.intent_id, "decision_id": i.decision_id,
        "risk_decision_id": i.risk_decision_id, "portfolio_decision_id": i.portfolio_decision_id,
        "symbol": i.symbol, "side": i.side.value, "action": i.action.value,
        "quantity": str(i.quantity), "order_type": i.order_type.value, "price": None,
        "execution_version": i.execution_version}
    return CapabilityAuthority(RuntimeAuthority()).issue(truth=t, requested_risk=Decimal("1"),
        decision_id=i.decision_id, intent_payload=payload, expires_at=now()+timedelta(minutes=1))


def test_commit_then_ack_then_fill():
    b = ExecutionBridge(); i = intent(); t = truth()
    x = b.commit_intent(capability=capability(), intent=i, truth=t, now=now(),
                        position_state=PositionState.FLAT, market_window=i.window,
                        upstream_windows=[i.window], risk_valid=True)
    assert x.status is BridgeStatus.COMMITTED
    ack = b.observe_ack(intent_id="i1", status="NEW", exchange_order_id="e1", client_order_id=x.client_order_id)
    assert ack.status is BridgeStatus.OBSERVED
    f = Fill("f1", x.order_request_id, "e1", Decimal("0.001"), Decimal("100000"), Decimal("0.10"))
    obs = b.apply_fill(intent=i, fill=f)
    assert obs.fill_ids == ("f1",)
    assert b.fill_ledger.total_quantity(x.order_request_id) == Decimal("0.001")


def test_unknown_blocks_retries_until_reconciled():
    b = ExecutionBridge(); i = intent(); t = truth()
    x = b.commit_intent(capability=capability(), intent=i, truth=t, now=now(),
                        position_state=PositionState.FLAT, market_window=i.window,
                        upstream_windows=[i.window], risk_valid=True)
    u = b.observe_ack(intent_id="i1", status="MYSTERY", exchange_order_id="e1", client_order_id=x.client_order_id)
    assert u.status is BridgeStatus.UNKNOWN
    with pytest.raises(ValueError, match="UNKNOWN_ORDER_NO_BLIND_RETRY"):
        b.require_reconciliation("i1")

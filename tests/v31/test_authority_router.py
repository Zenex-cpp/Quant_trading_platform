from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, CanonicalAction, build_truth
from trading_platform.v31.authority import RuntimeAuthority, AuthorityStatus

AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

def caps(v="100"):
    return {k: Decimal(v) for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}

def truth(status=TruthStatus.VERIFIED, *, fresh=True, kill=False):
    cs = tuple(TruthComponent(n, status, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    return build_truth(observed_at_ns=1, axes=AXES, components=cs, requested_risk=Decimal("100"), caps=caps(), kill_switch=kill, decision_fresh=fresh)

def test_trade_authorized_only_by_truth():
    a = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20"), decision_id="D1")
    assert a.status is AuthorityStatus.AUTHORIZED
    assert a.truth_hash == truth().state_hash

def test_trade_denied_when_truth_unknown():
    a = RuntimeAuthority().evaluate(truth=truth(TruthStatus.UNKNOWN), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="D2")
    assert not a.authorized
    assert a.reason == "TRUTH_UNKNOWN"

def test_trade_denied_when_requested_risk_exceeds_truth():
    t = build_truth(observed_at_ns=1, axes=AXES,
                    components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
                    requested_risk=Decimal("100"), caps=caps("10"))
    a = RuntimeAuthority().evaluate(truth=t, action=CanonicalAction.TRADE, requested_risk=Decimal("11"), decision_id="D3")
    assert a.reason == "RISK_EXCEEDS_OPERATIONAL_TRUTH"

def test_trade_denied_when_stale():
    a = RuntimeAuthority().evaluate(truth=truth(fresh=False), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="D4")
    assert a.reason == "TRUTH_STALE"

def test_trade_denied_by_kill_switch():
    a = RuntimeAuthority().evaluate(truth=truth(kill=True), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="D5")
    assert a.reason == "TRUTH_BLOCKED"

def test_decision_fingerprint_changes_with_inputs():
    r = RuntimeAuthority()
    a = r.evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="D6", input_payload={"symbol":"BTCUSDT"})
    b = r.evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="D6", input_payload={"symbol":"ETHUSDT"})
    assert a.input_fingerprint != b.input_fingerprint

def test_deploy_requires_truth():
    r = RuntimeAuthority()
    a = r.evaluate(truth=truth(), action=CanonicalAction.DEPLOY, decision_id="D7")
    assert a.authorized


def test_unknown_blocks_deploy():
    r = RuntimeAuthority()
    a = r.evaluate(truth=truth(TruthStatus.UNKNOWN), action=CanonicalAction.DEPLOY, decision_id="D8")
    assert not a.authorized
from trading_platform.v31.router import ExecutionRouter
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
WINDOW = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))

def intent():
    return OrderIntent("I1","D1","P1","R1","S1","M1","E1","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WINDOW)

def test_execution_router_requires_authority_for_order():
    t = truth()
    out = ExecutionRouter().route(intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT,
                                  market_window=WINDOW, upstream_windows=[WINDOW], risk_valid=True,
                                  requested_risk=Decimal("10"), decision_id="A1")
    assert out.authority.authorized
    assert out.request.order_request_id == "req:I1"

def test_execution_router_blocks_when_truth_unknown():
    with pytest.raises(PermissionError, match="TRUTH_UNKNOWN"):
        ExecutionRouter().route(intent=intent(), truth=truth(TruthStatus.UNKNOWN), now=NOW,
                                position_state=PositionState.FLAT, market_window=WINDOW,
                                upstream_windows=[WINDOW], risk_valid=True,
                                requested_risk=Decimal("1"), decision_id="A2")

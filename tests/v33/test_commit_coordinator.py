from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v33.commit import CommitCoordinator, CommitStatus
from trading_platform.v33.reconciliation import ReconciliationRequired
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
from trading_platform.core.ttl import ValidWindow

NOW=datetime(2026,9,13,tzinfo=timezone.utc)
WIN=ValidWindow(NOW-timedelta(seconds=1), NOW+timedelta(minutes=5))
AX=AxisSnapshot("ACTIVE","LIVE","HEALTHY","APPROVED","ACTIVE","CHAMPION")

def truth():
    return build_truth(observed_at_ns=1, axes=AX, components=tuple(TruthComponent(n,TruthStatus.VERIFIED,"OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")), requested_risk=Decimal("100"), caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})

def intent():
    return OrderIntent("I33","D33","P33","R33","S33","M33","E33","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WIN)

def payload():
    return {"intent_id":"I33","decision_id":"D33","risk_decision_id":"R33","portfolio_decision_id":"P33","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E33"}

def capability():
    t=truth(); return CapabilityAuthority().issue(truth=t, requested_risk=Decimal("10"), decision_id="D33", intent_payload=payload(), expires_at=NOW+timedelta(seconds=10)), t

def test_commit_consumes_once_and_transitions_submitted():
    c,t=capability(); cc=CommitCoordinator(capabilities=CapabilityAuthority())
    # re-issue from coordinator's own authority for a valid binding
    c=cc.capabilities.issue(truth=t,requested_risk=Decimal("10"),decision_id="D33",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    r=cc.commit(capability=c,intent=intent(),truth=t,now=NOW,position_state=PositionState.FLAT,market_window=WIN,upstream_windows=[WIN],risk_valid=True)
    assert r.status is CommitStatus.COMMITTED
    assert r.capability and r.capability.consumed
    assert cc.lifecycle_state("I33").value == "SUBMITTED"

def test_duplicate_returns_same_request_without_second_consumption():
    cc=CommitCoordinator(); t=truth(); i=intent()
    c=cc.capabilities.issue(truth=t,requested_risk=Decimal("10"),decision_id="D33",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    first=cc.commit(capability=c,intent=i,truth=t,now=NOW,position_state=PositionState.FLAT,market_window=WIN,upstream_windows=[WIN],risk_valid=True)
    second=cc.commit(capability=c,intent=i,truth=t,now=NOW,position_state=PositionState.FLAT,market_window=WIN,upstream_windows=[WIN],risk_valid=True)
    assert first.status is CommitStatus.COMMITTED and second.status is CommitStatus.DUPLICATE
    assert first.request == second.request

def test_unknown_position_forces_reconciliation_and_no_dispatch():
    cc=CommitCoordinator(); t=truth(); i=intent()
    c=cc.capabilities.issue(truth=t,requested_risk=Decimal("10"),decision_id="D33",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    with pytest.raises(ReconciliationRequired):
        cc.commit(capability=c,intent=i,truth=t,now=NOW,position_state=PositionState.UNKNOWN,market_window=WIN,upstream_windows=[WIN],risk_valid=True)

def test_marked_unknown_blocks_retry():
    cc=CommitCoordinator(); cc.mark_unknown("I33", client_order_id="cid")
    with pytest.raises(ValueError, match="UNKNOWN_ORDER_NO_BLIND_RETRY"):
        cc.assert_no_retry_until_reconciled("I33")

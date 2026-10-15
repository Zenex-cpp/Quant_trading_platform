from datetime import datetime, timezone, timedelta
from decimal import Decimal
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v32.router import CommitRouter
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
from trading_platform.core.ttl import ValidWindow
NOW=datetime(2026,9,13,tzinfo=timezone.utc); WIN=ValidWindow(NOW-timedelta(seconds=1), NOW+timedelta(minutes=5)); AX=AxisSnapshot("ACTIVE","LIVE","HEALTHY","APPROVED","ACTIVE","CHAMPION")
def truth(): return build_truth(observed_at_ns=1,axes=AX,components=tuple(TruthComponent(n,TruthStatus.VERIFIED,"OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),requested_risk=Decimal("100"),caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})
def intent(): return OrderIntent("I1","D1","P1","R1","S1","M1","E1","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WIN)
def payload(): return {"intent_id":"I1","decision_id":"D1","risk_decision_id":"R1","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E1"}
def test_commit_consumes_capability_and_routes():
    ca=CapabilityAuthority(); t=truth(); c=ca.issue(truth=t,requested_risk=Decimal("10"),decision_id="D1",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    out=CommitRouter(capability_authority=ca).commit(capability=c,intent=intent(),truth=t,now=NOW,position_state=PositionState.FLAT,market_window=WIN,upstream_windows=[WIN],risk_valid=True)
    assert out.capability.consumed and out.authorized_request.request.order_request_id=="req:I1"

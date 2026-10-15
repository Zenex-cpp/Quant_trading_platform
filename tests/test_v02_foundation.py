from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from trading_platform.execution.models import *
from trading_platform.execution.guards import build_order_request
from trading_platform.core.ttl import ValidWindow
from trading_platform.risk.budget import *
from trading_platform.risk.monotonicity import *
from trading_platform.state import *
from trading_platform.state.transition import *
from trading_platform.portfolio.config import *
from trading_platform.accounting.ledger import FillLedger
from trading_platform.research.methods import *

def window(now): return ValidWindow(now-timedelta(seconds=1), now+timedelta(seconds=10))

def test_unknown_position_blocks_new_order():
    now=datetime.now(timezone.utc); w=window(now)
    intent=OrderIntent("i","d","p","r","s","m","e","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("1"),OrderType.MARKET,w)
    with pytest.raises(ValueError, match="POSITION_UNKNOWN"):
        build_order_request(intent,now=now,position_state=PositionState.UNKNOWN,market_window=w,upstream_windows=[w],risk_valid=True)

def test_risk_reservation_is_atomic_and_not_double_consumed():
    ledger=RiskBudgetLedger(Decimal("10")); book=RiskReservationBook(); r=RiskReservation("r1",BudgetScope.ORDER,Decimal("3"),Decimal("3"))
    book.reserve(r,ledger); assert ledger.reserved==Decimal("3") and ledger.remaining()==Decimal("7")
    book.consume("r1",ledger); assert ledger.consumed==Decimal("3")
    with pytest.raises(ValueError): book.consume("r1",ledger)

def test_risk_monotonicity():
    better=adjusted_risk(Decimal("1"), uncertainty_factor=Decimal("1"), liquidity_factor=Decimal("1"))
    worse=adjusted_risk(Decimal("1"), uncertainty_factor=Decimal("0.5"), liquidity_factor=Decimal("0.5"))
    assert worse <= better
    assert_monotone_nonincrease(worse,better)

def test_transition_is_idempotent():
    a=OrthogonalState(Lifecycle.APPROVED,OperationalMode.RESEARCH,Health.HEALTHY,Approval.APPROVED,Deployment.ACTIVE,Role.CHAMPION)
    b=OrthogonalState(Lifecycle.APPROVED,OperationalMode.BACKTEST,Health.HEALTHY,Approval.APPROVED,Deployment.ACTIVE,Role.CHAMPION)
    e=TransitionEngine(); spec=TransitionSpec("t1",a,b,"START_BACKTEST",idempotency_key="k")
    assert e.apply(spec)==b; assert e.apply(spec)==b; assert len(e.audit)==1

def test_config_conflict():
    xs=[ConfigValue("x",1,Precedence.RUNTIME,"a","1"),ConfigValue("x",2,Precedence.RUNTIME,"b","1")]
    with pytest.raises(ValueError,match="CONFIG_CONFLICT"): resolve_config(xs)

def test_fill_not_double_counted():
    book=FillLedger(); f=Fill("f1","o1","x",Decimal("2"),Decimal("100"),Decimal("-0.1"))
    book.apply(f); book.apply(f); assert book.total_quantity("o1")==Decimal("2")

def test_method_not_applicable():
    spec=MethodSpec("m","1",("iid","stationarity"),"AR-like",())
    out=check_assumptions(spec,{"iid":False,"stationarity":True})
    assert out.status==MethodStatus.METHOD_NOT_APPLICABLE

from pathlib import Path
from decimal import Decimal

from trading_platform.v36.user_execution import BinanceExecutionCorrelation
from trading_platform.v313.durable_correlation import DurableExecutionCorrelationStore
from trading_platform.execution.lifecycle import OrderExecutionState, OrderLifecycle
from trading_platform.v34.execution_bridge import ExecutionBridge
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side

WINDOW = type("W", (), {})()

def intent(i="intent-1"):
    return OrderIntent(i,"d","p","r","s","m","v36","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WINDOW)

def payload():
    return {"e":"ORDER_TRADE_UPDATE","E":1000,"T":999,"o":{"s":"BTCUSDT","c":"cid-1","i":77,"x":"NEW","X":"NEW","t":0,"l":"0","L":"0","z":"0","n":"0","N":"USDT","T":1000}}

def bridge_seed():
    b=ExecutionBridge()
    b._requests["intent-1"] = type("Req", (), {"order_request_id":"or-1","client_order_id":"cid-1","symbol":"BTCUSDT"})()
    b._lifecycles["intent-1"] = OrderLifecycle()
    b._lifecycles["intent-1"].apply(OrderExecutionState.SUBMITTED,event_id="seed",idempotency_key="seed")
    return b

def test_user_execution_uses_durable_correlation_after_restart(tmp_path: Path):
    db=str(tmp_path/"corr.db")
    store=DurableExecutionCorrelationStore(db)
    b1=bridge_seed(); c1=BinanceExecutionCorrelation(b1,durable_store=store,now_epoch=lambda: 1.0)
    c1.register(intent=intent(),client_order_id="cid-1",order_request_id="or-1")
    c1.bind_exchange_order(intent_id="intent-1",exchange_order_id="77")
    assert c1.observe(payload()).correlated
    # New process-equivalent correlator: no in-memory mappings, durable store supplies identity.
    b2=bridge_seed(); c2=BinanceExecutionCorrelation(b2,durable_store=store,now_epoch=lambda: 2.0)
    assert c2.correlate(client_order_id="cid-1",exchange_order_id=None) == "intent-1"
    assert c2.correlate(client_order_id=None,exchange_order_id="77") == "intent-1"
    assert store.count_events() == 1
    store.close()

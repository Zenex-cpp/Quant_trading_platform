from decimal import Decimal
from datetime import datetime, timezone
import pytest

from trading_platform.accounting.ledger import FillLedger
from trading_platform.execution.models import Fill, OrderIntent, OrderAction, OrderType, Side
from trading_platform.core.ttl import ValidWindow
from trading_platform.v21.event_store import EventStore
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v339.fill_authority import DurableFillAuthority, FillIdentityConflict

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
WINDOW = ValidWindow(NOW, NOW.replace(second=1))

def _intent():
    return OrderIntent("i1","d1","p1","r1","s1","m1","v339","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("1"),OrderType.MARKET,WINDOW)

def _fill(fill_id="f1", trade_id="9", qty="0.4", price="100", fee="0.1"):
    return Fill(fill_id, "or1", "77", Decimal(qty), Decimal(price), Decimal(fee), trade_id=trade_id, venue="BINANCE")

def _bridge():
    b=ExecutionBridge()
    b._requests["i1"]=type("Req",(),{"order_request_id":"or1","client_order_id":"cid","symbol":"BTCUSDT"})()
    from trading_platform.execution.lifecycle import OrderLifecycle, OrderExecutionState
    b._lifecycles["i1"]=OrderLifecycle(); b._lifecycles["i1"].apply(OrderExecutionState.SUBMITTED,event_id="seed",idempotency_key="seed")
    return b

def test_duplicate_fill_does_not_mutate_position_or_pnl_twice():
    b=_bridge(); i=_intent(); f=_fill()
    r1=b.apply_fill(intent=i, fill=f); r2=b.apply_fill(intent=i, fill=f)
    assert r1.status is BridgeStatus.OBSERVED
    assert r2.status is BridgeStatus.DUPLICATE
    assert b.fill_ledger.total_quantity("or1") == Decimal("0.4")
    assert b.position_ledger.positions["BTCUSDT"].quantity == Decimal("0.4")
    assert len(b.pnl_ledger.entries()) == 1

def test_same_trade_identity_with_different_local_fill_id_is_idempotent_for_same_content():
    ledger=FillLedger()
    ledger.apply(_fill("local-1", "9"))
    entry, created = ledger.apply_once(_fill("local-2", "9"))
    assert not created
    assert entry.fill_id == "local-1"
    assert ledger.total_quantity("or1") == Decimal("0.4")

def test_same_trade_identity_with_incompatible_content_is_blocked():
    ledger=FillLedger()
    ledger.apply(_fill("local-1", "9"))
    with pytest.raises(ValueError, match="FILL_IDENTITY_REUSE_WITH_DIFFERENT_CONTENT"):
        ledger.apply(_fill("local-2", "9", qty="0.5"))

def test_durable_fill_authority_survives_restart_and_rejects_conflict(tmp_path):
    path=tmp_path/"fills.db"
    a=DurableFillAuthority(EventStore(str(path)))
    assert a.accept(_fill(), occurred_at_ms=1000).created
    b=DurableFillAuthority(EventStore(str(path)))
    assert not b.accept(_fill("other-local-id"), occurred_at_ms=1001).created
    with pytest.raises(FillIdentityConflict):
        b.accept(_fill("third", "9", qty="0.5"), occurred_at_ms=1002)
    assert b.store.verify_chain()

def test_bridge_durable_authority_blocks_second_source_after_restart(tmp_path):
    path=tmp_path/"fills.db"
    b1=_bridge(); b1.fill_authority=DurableFillAuthority(EventStore(str(path)))
    first=b1.apply_fill(intent=_intent(), fill=_fill("stream-fill"))
    assert first.status is BridgeStatus.OBSERVED
    b2=_bridge(); b2.fill_authority=DurableFillAuthority(EventStore(str(path)))
    duplicate=b2.apply_fill(intent=_intent(), fill=_fill("rest-fill"))
    assert duplicate.status is BridgeStatus.DUPLICATE
    assert b2.position_ledger.positions.get("BTCUSDT") is None

def test_durable_accounting_uses_venue_trade_identity(tmp_path):
    from trading_platform.v315.durable_accounting import DurableAccountingLedger, DurableFill
    ledger = DurableAccountingLedger(EventStore(str(tmp_path / "acct.db")))
    one = DurableFill("local-1", "or1", "BTCUSDT", "BUY", Decimal("0.4"), Decimal("100"), Decimal("0.1"), occurred_at_ms=1000, exchange_order_id="77", trade_id="9", venue="BINANCE")
    two = DurableFill("local-2", "or1", "BTCUSDT", "BUY", Decimal("0.4"), Decimal("100"), Decimal("0.1"), occurred_at_ms=1001, exchange_order_id="77", trade_id="9", venue="BINANCE")
    first, created = ledger.append_fill_once(one)
    second, created2 = ledger.append_fill_once(two)
    assert created and not created2
    assert first.event_id == second.event_id
    assert ledger.reconstruct().positions[0].quantity == Decimal("0.4")

def test_binance_trade_identity_is_carried_into_normalized_fill():
    from trading_platform.v36.user_execution import parse_order_trade_update
    from trading_platform.v36.user_execution import BinanceExecutionCorrelation
    b, c = _bridge(), BinanceExecutionCorrelation(_bridge())
    update = parse_order_trade_update({
        "e":"ORDER_TRADE_UPDATE","E":1000,"T":999,
        "o":{"s":"BTCUSDT","c":"cid","i":77,"x":"TRADE","X":"FILLED","t":9,"l":"0.4","L":"100","z":"0.4","n":"0.1","N":"USDT","T":1000}
    })
    assert update.trade_id == "9"
    assert update.is_trade

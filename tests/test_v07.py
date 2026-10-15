from decimal import Decimal as D
from datetime import datetime, timezone
import pytest
from trading_platform.realtime.orderbook import OrderBook, OrderBookSnapshot, OrderBookDiff
from trading_platform.realtime.microstructure import compute_microstructure
from trading_platform.realtime.clock import check_clock_integrity, ClockHealth
from trading_platform.realtime.adapter import RateLimitBudget

def snap():
    return OrderBookSnapshot(100, ((D('100'),D('5')),(D('99'),D('4'))), ((D('101'),D('6')),(D('102'),D('7'))))

def test_orderbook_snapshot_and_contiguous_diff():
    b=OrderBook('BTCUSDT'); b.load_snapshot(snap())
    b.apply_diff(OrderBookDiff(101,102,((D('100'),D('7')),),((D('101'),D('5')),)))
    assert b.last_update_id==102 and b.best_bid()==D('100') and b.best_ask()==D('101')

def test_orderbook_duplicate_is_idempotent():
    b=OrderBook('BTCUSDT'); b.load_snapshot(snap())
    d=OrderBookDiff(101,101,((D('100'),D('7')),),())
    b.apply_diff(d); before=dict(b.bids); b.apply_diff(d); assert b.bids==before

def test_orderbook_gap_blocks():
    b=OrderBook('BTCUSDT'); b.load_snapshot(snap())
    with pytest.raises(ValueError, match='ORDERBOOK_SEQUENCE_GAP'): b.apply_diff(OrderBookDiff(103,103,(),()))
    assert b.status.value=='GAP_DETECTED'

def test_crossed_snapshot_blocked():
    b=OrderBook('BTCUSDT')
    with pytest.raises(ValueError, match='CROSSED_ORDERBOOK'):
        b.load_snapshot(OrderBookSnapshot(1,((D('102'),D('1')),),((D('101'),D('1')),)))

def test_microstructure():
    b=OrderBook('BTCUSDT'); b.load_snapshot(snap()); m=compute_microstructure(b)
    assert m.mid==D('100.5') and m.spread==D('1') and m.imbalance==D('-0.1818181818181818181818181818')

def test_clock_invalid_offset():
    x=check_clock_integrity(source_time=datetime.now(timezone.utc), wall_clock=datetime.now(timezone.utc), ntp_offset_ms=50, max_allowed_offset_ms=10)
    assert x.health==ClockHealth.INVALID

def test_rate_limit_budget():
    t=datetime.now(timezone.utc)
    b=RateLimitBudget(10,7,1,t)
    assert b.remaining()==3
    b2=b.reserve(3)
    assert b2.remaining()==0
    with pytest.raises(ValueError, match='RATE_LIMIT_EXCEEDED'): b2.reserve(1)

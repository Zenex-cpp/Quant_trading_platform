from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent
from trading_platform.v378 import (
    BinanceTimeInForce,
    BinanceVenueExecutionEngine,
    BinanceVenueExecutionModelConfig,
    MarketTrade,
    VenueMarketEvent,
    VenueRejectReason,
)

SYMBOL = "BTCUSDT"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def market(offset: int, close: str = "100") -> MarketEvent:
    p = Decimal(close)
    return MarketEvent(
        event_offset=offset,
        event_time=BASE_TIME,
        symbol=SYMBOL,
        open=p,
        high=p,
        low=p,
        close=p,
        volume=Decimal("100"),
    )


def book(offset: int, bid_qty: str = "10", ask_qty: str = "10") -> OrderBookSnapshot:
    return OrderBookSnapshot(
        last_update_id=100 + offset,
        bids=((Decimal("99"), Decimal(bid_qty)), (Decimal("98"), Decimal("20"))),
        asks=((Decimal("101"), Decimal(ask_qty)), (Decimal("102"), Decimal("20"))),
    )


def wrapper(offset: int, trades=(), bid_qty: str = "10", ask_qty: str = "10") -> VenueMarketEvent:
    return VenueMarketEvent(market=market(offset), book=book(offset, bid_qty, ask_qty), trades=tuple(trades))


def window() -> ValidWindow:
    return ValidWindow(
        valid_from=BASE_TIME,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def stage(intent: OrderIntent | None) -> BacktestStageFunctions:
    def intent_fn(event, risk):
        if event.event_offset == 0:
            return intent
        return None

    return BacktestStageFunctions(
        feature_fn=lambda e: None,
        regime_fn=lambda e, f: None,
        prediction_fn=lambda e, f, r: None,
        signal_fn=lambda e, p: None,
        opportunity_fn=lambda e, s, r: None,
        portfolio_fn=lambda e, o, q: None,
        risk_fn=lambda e, p, q: None,
        intent_fn=intent_fn,
    )


def intent(
    *,
    side: Side = Side.BUY,
    qty: str = "5",
    order_type: OrderType = OrderType.MARKET,
    price: str | None = None,
    tif: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        intent_id="I1",
        decision_id="D1",
        portfolio_decision_id="P1",
        risk_decision_id="R1",
        strategy_id="S1",
        model_id="M1",
        execution_version="VX-1",
        symbol=SYMBOL,
        side=side,
        action=OrderAction.OPEN,
        quantity=Decimal(qty),
        order_type=order_type,
        price=Decimal(price) if price is not None else None,
        time_in_force=tif,
        window=window(),
    )


def model() -> BinanceVenueExecutionModelConfig:
    return BinanceVenueExecutionModelConfig(
        version="VX-1",
        venue="BINANCE_USDM",
        symbol=SYMBOL,
        maker_fee_bps=Decimal("1"),
        taker_fee_bps=Decimal("2"),
    )


def run(i: OrderIntent, events):
    return BinanceVenueExecutionEngine(stage(i), model(), SYMBOL).run(events)


def test_market_order_sweeps_multiple_book_levels_and_uses_taker_fee():
    result = run(intent(qty="15"), [wrapper(0, ask_qty="10")])
    assert [f.quantity for f in result.fills] == [Decimal("10"), Decimal("5")]
    assert [f.price for f in result.fills] == [Decimal("101"), Decimal("102")]
    # 15 BTC/USDT notional weighted fee = 0.303 USDT at 2 bps.
    assert sum((f.fee for f in result.fills), Decimal("0")) == Decimal("0.304")
    assert result.final_quantity == Decimal("15")


def test_gtx_marketable_order_is_rejected_with_binance_code():
    result = run(
        intent(order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.GTX.value),
        [wrapper(0)],
    )
    assert len(result.fills) == 0
    assert result.rejections[0].reason is VenueRejectReason.GTX_ORDER_REJECT
    assert result.rejections[0].exchange_code == "-5022"


def test_fok_rejects_when_book_cannot_fully_fill():
    result = run(
        intent(qty="12", order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.FOK.value),
        [wrapper(0, ask_qty="10")],
    )
    assert result.fills == ()
    assert result.rejections[0].reason is VenueRejectReason.FOK_ORDER_REJECT
    assert result.rejections[0].exchange_code == "-5021"


def test_ioc_partially_fills_and_cancels_remainder():
    result = run(
        intent(qty="12", order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.IOC.value),
        [wrapper(0, ask_qty="10")],
    )
    assert sum((f.quantity for f in result.fills), Decimal("0")) == Decimal("10")
    assert result.cancelled_remainders == (("I1", Decimal("2"), "IOC_REMAINDER"),)


def test_gtc_resting_order_waits_behind_displayed_queue_and_then_fills():
    i = intent(qty="3", order_type=OrderType.LIMIT, price="99", tif=BinanceTimeInForce.GTC.value)
    first = wrapper(0)
    second = wrapper(
        1,
        trades=(MarketTrade("T1", Decimal("99"), Decimal("13"), Side.SELL),),
    )
    result = BinanceVenueExecutionEngine(stage(i), model(), SYMBOL).run([first, second])
    assert [f.quantity for f in result.fills] == [Decimal("3")]
    assert result.fills[0].trade_id == "T1"
    assert result.fills[0].fee == Decimal("0.0297")
    assert result.open_orders == ()


def test_queue_ahead_is_carried_when_trade_does_not_reach_our_order():
    i = intent(qty="3", order_type=OrderType.LIMIT, price="99", tif=BinanceTimeInForce.GTC.value)
    result = BinanceVenueExecutionEngine(stage(i), model(), SYMBOL).run(
        [wrapper(0), wrapper(1, trades=(MarketTrade("T1", Decimal("99"), Decimal("5"), Side.SELL),))]
    )
    assert result.fills == ()
    assert result.open_orders == (("I1", Decimal("3"), Decimal("5")),)


def test_rpi_is_fail_closed_without_rpi_liquidity_model():
    i = intent(order_type=OrderType.LIMIT, price="99", tif=BinanceTimeInForce.RPI.value)
    result = run(i, [wrapper(0)])
    assert result.fills == ()
    assert result.rejections[0].reason is VenueRejectReason.RPI_LIQUIDITY_MODEL_UNSUPPORTED


def test_orderbook_update_regression_is_rejected():
    bad_book = OrderBookSnapshot(
        last_update_id=99,
        bids=((Decimal("99"), Decimal("10")),),
        asks=((Decimal("101"), Decimal("10")),),
    )
    bad_event = VenueMarketEvent(market=market(1), book=bad_book)
    with pytest.raises(ValueError, match="ORDERBOOK_UPDATE_ID_REVERSED"):
        BinanceVenueExecutionEngine(stage(intent()), model(), SYMBOL).run([wrapper(0), bad_event])


def test_execution_is_deterministic():
    i = intent(qty="7")
    events = [wrapper(0, ask_qty="4"), wrapper(1)]
    r1 = run(i, events)
    r2 = run(i, events)
    assert r1.state_hash == r2.state_hash
    assert r1.fills == r2.fills


def test_non_exact_determinism_is_rejected_for_venue_model():
    with pytest.raises(ValueError, match="VENUE_MODEL_REQUIRES_EXACT_DETERMINISM"):
        BinanceVenueExecutionModelConfig(
            version="BAD",
            determinism=DeterminismClass.STOCHASTIC_BUT_SEEDED,
        )

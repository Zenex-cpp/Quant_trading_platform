"""V3.78 venue-realistic execution model (§86).

Adds deterministic order-book depth, a conservative price-time queue proxy,
maker/taker fees, time-in-force semantics, and Binance USDⓈ-M-style rejection
semantics to the v3.x backtest path without mutating historical engines.

This is a simulation model, not an exchange implementation. Queue position is
estimated from displayed L2 quantity at submission plus subsequent aggressor
trades at the order price. L2 cancellations/replacements and hidden liquidity
are not reconstructed; new arrivals ahead are not inferred from L2 snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from trading_platform.core.nonfinite import assert_finite
from trading_platform.execution.models import Fill, OrderIntent, OrderType, Side
from trading_platform.realtime.orderbook import OrderBook, OrderBookSnapshot
from trading_platform.replay.replay import canonical_hash
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    DeterminismClass,
    MarketEvent,
    OutOfOrderEventError,
)


class BinanceTimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"  # Post Only
    RPI = "RPI"  # Separate liquidity pool; not simulated here.


class VenueRejectReason(str, Enum):
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    INVALID_TIME_IN_FORCE = "INVALID_TIME_IN_FORCE"
    RPI_LIQUIDITY_MODEL_UNSUPPORTED = "RPI_LIQUIDITY_MODEL_UNSUPPORTED"
    GTX_ORDER_REJECT = "GTX_ORDER_REJECT"
    FOK_ORDER_REJECT = "FOK_ORDER_REJECT"
    NO_LIQUIDITY = "NO_LIQUIDITY"
    INVALID_LIMIT_PRICE = "INVALID_LIMIT_PRICE"


@dataclass(frozen=True)
class MarketTrade:
    trade_id: str
    price: Decimal
    quantity: Decimal
    aggressor_side: Side

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("TRADE_ID_REQUIRED")
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("INVALID_MARKET_TRADE")
        assert_finite(float(self.price), float(self.quantity))


@dataclass(frozen=True)
class VenueMarketEvent:
    market: MarketEvent
    book: OrderBookSnapshot
    trades: tuple[MarketTrade, ...] = ()

    def __post_init__(self) -> None:
        validator = OrderBook(symbol=self.market.symbol)
        validator.load_snapshot(self.book)
        for trade in self.trades:
            if trade.price <= 0 or trade.quantity <= 0:
                raise ValueError("INVALID_MARKET_TRADE")


@dataclass(frozen=True)
class BinanceVenueExecutionModelConfig:
    """Versioned simulation assumptions for Binance USDⓈ-M-style execution."""

    version: str
    venue: str = "BINANCE_USDM"
    symbol: str = "BTCUSDT"
    maker_fee_bps: Decimal = Decimal("0")
    taker_fee_bps: Decimal = Decimal("0")
    latency_offsets: int = 0
    queue_model_version: str = "PRICE_TIME_L2_V1"
    determinism: DeterminismClass = DeterminismClass.EXACT
    rpi_supported: bool = False

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("VENUE_EXECUTION_MODEL_VERSION_REQUIRED")
        if not self.venue or not self.symbol:
            raise ValueError("VENUE_AND_SYMBOL_REQUIRED")
        if self.maker_fee_bps < 0 or self.taker_fee_bps < 0:
            raise ValueError("INVALID_VENUE_FEE")
        if self.latency_offsets < 0:
            raise ValueError("INVALID_LATENCY_OFFSET")
        if not self.queue_model_version:
            raise ValueError("QUEUE_MODEL_VERSION_REQUIRED")
        if self.determinism == DeterminismClass.STOCHASTIC_BUT_SEEDED:
            raise ValueError("VENUE_MODEL_REQUIRES_EXACT_DETERMINISM")


@dataclass
class _RestingOrder:
    intent: OrderIntent
    remaining_quantity: Decimal
    queue_ahead: Decimal


@dataclass(frozen=True)
class VenueRejection:
    intent_id: str
    event_offset: int
    reason: VenueRejectReason
    exchange_code: str | None = None


@dataclass(frozen=True)
class VenueExecutionResult:
    fills: tuple[Fill, ...]
    rejections: tuple[VenueRejection, ...]
    cancelled_remainders: tuple[tuple[str, Decimal, str], ...]
    open_orders: tuple[tuple[str, Decimal, Decimal], ...]
    final_quantity: Decimal
    final_equity: Decimal
    state_hash: str
    event_count: int
    execution_model_version: str


@dataclass(frozen=True)
class _OrderOutcome:
    fills: tuple[Fill, ...] = ()
    rejection: VenueRejection | None = None
    remainder: Decimal = Decimal("0")
    remainder_reason: str | None = None
    queue_ahead: Decimal = Decimal("0")


class BinanceVenueExecutionEngine:
    """Depth-aware deterministic execution engine for BTCUSDT simulation."""

    def __init__(
        self,
        stages: BacktestStageFunctions,
        execution_model: BinanceVenueExecutionModelConfig,
        symbol: str,
        seed: int = 0,
    ) -> None:
        if symbol != execution_model.symbol:
            raise ValueError("VENUE_SYMBOL_CONFIGURATION_MISMATCH")
        self._stages = stages
        self._execution_model = execution_model
        self._symbol = symbol
        self._seed = seed

    def run(self, events: Sequence[VenueMarketEvent]) -> VenueExecutionResult:
        ledger_quantity = Decimal("0")
        ledger_cash = Decimal("0")
        fills: list[Fill] = []
        rejections: list[VenueRejection] = []
        cancellations: list[tuple[str, Decimal, str]] = []
        resting: list[_RestingOrder] = []
        delayed: list[tuple[int, OrderIntent]] = []
        equity_curve: list[Decimal] = []
        last_event_offset = -1
        last_book_update_id = -1

        for wrapper in events:
            event = wrapper.market
            if event.event_offset <= last_event_offset:
                raise OutOfOrderEventError(
                    f"event_offset {event.event_offset} must exceed {last_event_offset}"
                )
            last_event_offset = event.event_offset
            if wrapper.book.last_update_id < last_book_update_id:
                raise ValueError("ORDERBOOK_UPDATE_ID_REVERSED")
            last_book_update_id = wrapper.book.last_update_id
            if event.symbol != self._symbol:
                raise ValueError("MARKET_EVENT_SYMBOL_MISMATCH")

            # Live-equivalent decision path.
            feature = self._stages.feature_fn(event)
            regime = self._stages.regime_fn(event, feature)
            prediction = self._stages.prediction_fn(event, feature, regime)
            signal = self._stages.signal_fn(event, prediction)
            opportunity = self._stages.opportunity_fn(event, signal, regime)
            portfolio = self._stages.portfolio_fn(event, opportunity, ledger_quantity)
            risk = self._stages.risk_fn(event, portfolio, ledger_quantity)
            intent = self._stages.intent_fn(event, risk)

            # Passive orders receive fills from explicitly supplied aggressor trades.
            ledger_quantity, ledger_cash = self._process_resting(
                wrapper.trades, event, resting, fills, ledger_quantity, ledger_cash
            )

            if intent is not None:
                if self._execution_model.latency_offsets > 0:
                    delayed.append((event.event_offset + self._execution_model.latency_offsets, intent))
                else:
                    outcome = self._execute_new_order(intent, wrapper.book, event, len(fills))
                    ledger_quantity, ledger_cash = self._apply_fills(
                        outcome.fills, intent.side, ledger_quantity, ledger_cash
                    )
                    fills.extend(outcome.fills)
                    if outcome.rejection:
                        rejections.append(outcome.rejection)
                    self._record_remainder(
                        outcome, intent, resting, cancellations
                    )

            # Activate any latency-delayed intents at this event boundary.
            ready = [item for item in delayed if item[0] <= event.event_offset]
            delayed = [item for item in delayed if item[0] > event.event_offset]
            for _, pending_intent in ready:
                outcome = self._execute_new_order(pending_intent, wrapper.book, event, len(fills))
                ledger_quantity, ledger_cash = self._apply_fills(
                    outcome.fills, pending_intent.side, ledger_quantity, ledger_cash
                )
                fills.extend(outcome.fills)
                if outcome.rejection:
                    rejections.append(outcome.rejection)
                self._record_remainder(outcome, pending_intent, resting, cancellations)

            equity = ledger_cash + ledger_quantity * event.close
            assert_finite(float(equity))
            equity_curve.append(equity)

        open_orders = tuple(
            sorted(
                (
                    o.intent.intent_id,
                    o.remaining_quantity,
                    o.queue_ahead,
                )
                for o in resting
                if o.remaining_quantity > 0
            )
        )
        final_equity = equity_curve[-1] if equity_curve else ledger_cash
        state = {
            "symbol": self._symbol,
            "venue": self._execution_model.venue,
            "execution_model_version": self._execution_model.version,
            "queue_model_version": self._execution_model.queue_model_version,
            "fills": [
                {
                    "fill_id": f.fill_id,
                    "quantity": str(f.quantity),
                    "price": str(f.price),
                    "fee": str(f.fee),
                    "trade_id": f.trade_id,
                }
                for f in fills
            ],
            "rejections": [
                {
                    "intent_id": r.intent_id,
                    "offset": r.event_offset,
                    "reason": r.reason.value,
                    "exchange_code": r.exchange_code,
                }
                for r in rejections
            ],
            "cancelled": [(i, str(q), reason) for i, q, reason in cancellations],
            "open_orders": [(i, str(q), str(ahead)) for i, q, ahead in open_orders],
            "final_quantity": str(ledger_quantity),
            "final_equity": str(final_equity),
            "seed": self._seed,
            "event_count": len(events),
        }
        return VenueExecutionResult(
            fills=tuple(fills),
            rejections=tuple(rejections),
            cancelled_remainders=tuple(cancellations),
            open_orders=open_orders,
            final_quantity=ledger_quantity,
            final_equity=final_equity,
            state_hash=canonical_hash(state),
            event_count=len(events),
            execution_model_version=self._execution_model.version,
        )

    def _execute_new_order(
        self,
        intent: OrderIntent,
        book: OrderBookSnapshot,
        event: MarketEvent,
        fill_sequence_start: int,
    ) -> _OrderOutcome:
        tif = (intent.time_in_force or BinanceTimeInForce.GTC.value).upper()
        if tif not in {v.value for v in BinanceTimeInForce}:
            return _OrderOutcome(
                rejection=VenueRejection(
                    intent.intent_id, event.event_offset, VenueRejectReason.INVALID_TIME_IN_FORCE
                )
            )
        if tif == BinanceTimeInForce.RPI.value and not self._execution_model.rpi_supported:
            return _OrderOutcome(
                rejection=VenueRejection(
                    intent.intent_id,
                    event.event_offset,
                    VenueRejectReason.RPI_LIQUIDITY_MODEL_UNSUPPORTED,
                )
            )
        if intent.order_type == OrderType.LIMIT and (intent.price is None or intent.price <= 0):
            return _OrderOutcome(
                rejection=VenueRejection(
                    intent.intent_id, event.event_offset, VenueRejectReason.INVALID_LIMIT_PRICE
                )
            )

        marketable = intent.order_type == OrderType.MARKET or self._is_marketable(intent, book)
        if tif == BinanceTimeInForce.GTX.value and marketable:
            return _OrderOutcome(
                rejection=VenueRejection(
                    intent.intent_id,
                    event.event_offset,
                    VenueRejectReason.GTX_ORDER_REJECT,
                    exchange_code="-5022",
                )
            )

        levels = self._opposite_levels(intent, book)
        if intent.order_type == OrderType.LIMIT and intent.price is not None:
            if intent.side == Side.BUY:
                levels = [(p, q) for p, q in levels if p <= intent.price]
            else:
                levels = [(p, q) for p, q in levels if p >= intent.price]
        available = sum((q for _, q in levels), Decimal("0"))

        if tif == BinanceTimeInForce.FOK.value and available < intent.quantity:
            return _OrderOutcome(
                rejection=VenueRejection(
                    intent.intent_id,
                    event.event_offset,
                    VenueRejectReason.FOK_ORDER_REJECT,
                    exchange_code="-5021",
                )
            )

        fillable = min(intent.quantity, available)
        if fillable <= 0:
            if tif in {BinanceTimeInForce.IOC.value, BinanceTimeInForce.FOK.value} or intent.order_type == OrderType.MARKET:
                return _OrderOutcome(
                    rejection=VenueRejection(
                        intent.intent_id, event.event_offset, VenueRejectReason.NO_LIQUIDITY
                    )
                )
            return _OrderOutcome(
                remainder=intent.quantity,
                remainder_reason="RESTING_GTC",
                queue_ahead=self._queue_ahead(book, intent),
            )

        maker = (not marketable) and intent.order_type == OrderType.LIMIT
        remaining = intent.quantity
        fills_out: list[Fill] = []
        for level_index, (price, qty) in enumerate(levels):
            if remaining <= 0:
                break
            this_qty = min(remaining, qty)
            fee_bps = self._execution_model.maker_fee_bps if maker else self._execution_model.taker_fee_bps
            fee = price * this_qty * fee_bps / Decimal("10000")
            fill = Fill(
                fill_id=f"{self._execution_model.venue}-{event.event_offset}-{intent.intent_id}-{fill_sequence_start+level_index}",
                order_request_id=intent.intent_id,
                exchange_order_id=f"SIM-{event.event_offset}-{intent.intent_id}",
                quantity=this_qty,
                price=price,
                fee=fee,
                event_time=event.event_time,
                trade_id=None,
                venue=self._execution_model.venue,
            )
            fills_out.append(fill)
            remaining -= this_qty

        if remaining <= 0:
            return _OrderOutcome(fills=tuple(fills_out))

        if tif == BinanceTimeInForce.IOC.value:
            return _OrderOutcome(
                fills=tuple(fills_out), remainder=remaining, remainder_reason="IOC_REMAINDER"
            )
        if tif == BinanceTimeInForce.FOK.value:
            # FOK was checked before matching, so this cannot occur unless the
            # input book is internally inconsistent.
            raise AssertionError("FOK_FILL_ACCOUNTING_INVARIANT")
        if intent.order_type == OrderType.LIMIT and tif == BinanceTimeInForce.GTC.value:
            return _OrderOutcome(
                fills=tuple(fills_out),
                remainder=remaining,
                remainder_reason="RESTING_GTC",
                queue_ahead=Decimal("0") if marketable else self._queue_ahead(book, intent),
            )
        return _OrderOutcome(fills=tuple(fills_out), remainder=remaining, remainder_reason="IOC_REMAINDER")

    @staticmethod
    def _record_remainder(
        outcome: _OrderOutcome,
        intent: OrderIntent,
        resting: list[_RestingOrder],
        cancellations: list[tuple[str, Decimal, str]],
    ) -> None:
        if outcome.remainder <= 0:
            return
        if outcome.remainder_reason == "RESTING_GTC":
            resting.append(
                _RestingOrder(
                    intent=intent,
                    remaining_quantity=outcome.remainder,
                    queue_ahead=outcome.queue_ahead,
                )
            )
        else:
            cancellations.append((intent.intent_id, outcome.remainder, outcome.remainder_reason or "CANCELLED"))

    def _process_resting(
        self,
        trades: Sequence[MarketTrade],
        event: MarketEvent,
        resting: list[_RestingOrder],
        fills: list[Fill],
        ledger_quantity: Decimal,
        ledger_cash: Decimal,
    ) -> tuple[Decimal, Decimal]:
        for trade in trades:
            for order in list(resting):
                if order.intent.order_type != OrderType.LIMIT or order.intent.price is None:
                    continue
                if order.intent.side == Side.BUY and trade.aggressor_side != Side.SELL:
                    continue
                if order.intent.side == Side.SELL and trade.aggressor_side != Side.BUY:
                    continue
                if trade.price != order.intent.price:
                    continue
                consumed_ahead = min(order.queue_ahead, trade.quantity)
                order.queue_ahead -= consumed_ahead
                executable = trade.quantity - consumed_ahead
                if executable <= 0 or order.remaining_quantity <= 0:
                    continue
                fill_qty = min(order.remaining_quantity, executable)
                fee = trade.price * fill_qty * self._execution_model.maker_fee_bps / Decimal("10000")
                fill = Fill(
                    fill_id=f"{self._execution_model.venue}-{event.event_offset}-{order.intent.intent_id}-{len(fills)}",
                    order_request_id=order.intent.intent_id,
                    exchange_order_id=f"SIM-{event.event_offset}-{order.intent.intent_id}",
                    quantity=fill_qty,
                    price=trade.price,
                    fee=fee,
                    event_time=event.event_time,
                    trade_id=trade.trade_id,
                    venue=self._execution_model.venue,
                )
                fills.append(fill)
                order.remaining_quantity -= fill_qty
                ledger_quantity, ledger_cash = self._apply_fills(
                    (fill,), order.intent.side, ledger_quantity, ledger_cash
                )
                if order.remaining_quantity <= 0:
                    resting.remove(order)
        return ledger_quantity, ledger_cash

    @staticmethod
    def _apply_fills(
        fills: Sequence[Fill],
        side: Side,
        ledger_quantity: Decimal,
        ledger_cash: Decimal,
    ) -> tuple[Decimal, Decimal]:
        for fill in fills:
            notional = fill.price * fill.quantity
            if side == Side.BUY:
                ledger_cash -= notional
                ledger_quantity += fill.quantity
            else:
                ledger_cash += notional
                ledger_quantity -= fill.quantity
            ledger_cash -= fill.fee
        assert_finite(float(ledger_quantity), float(ledger_cash))
        return ledger_quantity, ledger_cash

    @staticmethod
    def _opposite_levels(intent: OrderIntent, book: OrderBookSnapshot) -> list[tuple[Decimal, Decimal]]:
        return list(book.asks if intent.side == Side.BUY else book.bids)

    @staticmethod
    def _is_marketable(intent: OrderIntent, book: OrderBookSnapshot) -> bool:
        if intent.order_type == OrderType.MARKET:
            return True
        if intent.price is None:
            return False
        if intent.side == Side.BUY:
            best = min((p for p, q in book.asks if q > 0), default=None)
            return best is not None and intent.price >= best
        best = max((p for p, q in book.bids if q > 0), default=None)
        return best is not None and intent.price <= best

    @staticmethod
    def _queue_ahead(book: OrderBookSnapshot, intent: OrderIntent) -> Decimal:
        if intent.price is None:
            return Decimal("0")
        levels = book.bids if intent.side == Side.BUY else book.asks
        for price, quantity in levels:
            if price == intent.price:
                return quantity
        return Decimal("0")

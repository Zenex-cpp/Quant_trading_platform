"""V3.76 — deterministic liquidity-constrained partial-fill execution (§86).

V3.74 introduced a liquidity participation cap for STRESS mode, but its
contract was intentionally all-or-nothing: an order above the cap was
rejected rather than partially filled. V3.76 closes that specific execution
model gap without editing any previously shipped version.

The new engine reuses the same `BacktestStageFunctions` contract and the same
market-event schema as V3.73. It adds only the execution-layer behavior that
requires a different event loop: an eligible order can remain pending after a
partial fill and consume additional bar volume on later events until it is
filled, expires, or the input stream ends.

This module does not implement order-book levels, queue position, venue
matching, maker/taker semantics, or exchange-specific reject codes. The
participation rate is an explicit simulation assumption, not a market-calibrated
claim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from trading_platform.core.nonfinite import assert_finite
from trading_platform.execution.models import Fill, OrderIntent, Side
from trading_platform.replay.replay import canonical_hash
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    OutOfOrderEventError,
    RejectedIntent,
    RejectionReason,
    SimulationMode,
)


class PartialFillRejectionReason(str, Enum):
    WINDOW_EXPIRED = "PARTIAL_FILL_WINDOW_EXPIRED"


@dataclass(frozen=True)
class PartialFillExecutionModelConfig(ExecutionModelConfig):
    """§86 partial-fill execution configuration."""

    participation_rate: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        # Reuse the published V3.73 validation contract exactly, then apply
        # the new execution-layer constraint.
        ExecutionModelConfig.__post_init__(self)
        if self.mode == SimulationMode.STRESS:
            raise ValueError("PARTIAL_FILL_EXECUTION_MODE_UNSUPPORTED_FOR_STRESS")
        if not (Decimal("0") < self.participation_rate <= Decimal("1")):
            raise ValueError("INVALID_PARTICIPATION_RATE")


@dataclass(frozen=True)
class PartialFillBacktestResult:
    fills: tuple[Fill, ...]
    rejected_intents: tuple[RejectedIntent, ...]
    open_orders: tuple[tuple[str, Decimal], ...]
    equity_curve: tuple[Decimal, ...]
    final_equity: Decimal
    final_quantity: Decimal
    event_count: int
    state_hash: str
    execution_model_version: str
    mode: SimulationMode


@dataclass
class _Ledger:
    quantity: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")

    def equity(self, mark_price: Decimal) -> Decimal:
        return self.cash + self.quantity * mark_price


@dataclass
class _PendingOrder:
    ready_offset: int
    intent: OrderIntent
    remaining_quantity: Decimal
    fill_index: int = 0


class PartialFillBacktestEngine:
    """Event-driven execution engine with deterministic partial fills."""

    def __init__(
        self,
        stages: BacktestStageFunctions,
        execution_model: PartialFillExecutionModelConfig,
        symbol: str,
        seed: int = 0,
    ) -> None:
        if not isinstance(execution_model, PartialFillExecutionModelConfig):
            raise ValueError("PARTIAL_FILL_ENGINE_REQUIRES_PARTIAL_FILL_EXECUTION_MODEL")
        self._stages = stages
        self._execution_model = execution_model
        self._symbol = symbol
        self._seed = seed

    def run(self, market_events: Sequence[MarketEvent]) -> PartialFillBacktestResult:
        ledger = _Ledger()
        fills: list[Fill] = []
        rejected: list[RejectedIntent] = []
        equity_curve: list[Decimal] = []
        pending: list[_PendingOrder] = []
        last_offset = -1

        for event in market_events:
            if event.event_offset <= last_offset:
                raise OutOfOrderEventError(
                    f"event_offset {event.event_offset} must exceed {last_offset}"
                )
            last_offset = event.event_offset

            feature = self._stages.feature_fn(event)
            regime = self._stages.regime_fn(event, feature)
            prediction = self._stages.prediction_fn(event, feature, regime)
            signal = self._stages.signal_fn(event, prediction)
            opportunity = self._stages.opportunity_fn(event, signal, regime)
            portfolio_decision = self._stages.portfolio_fn(event, opportunity, ledger.quantity)
            risk_decision = self._stages.risk_fn(event, portfolio_decision, ledger.quantity)
            intent: Optional[OrderIntent] = self._stages.intent_fn(event, risk_decision)
            if intent is not None:
                pending.append(
                    _PendingOrder(
                        ready_offset=event.event_offset + self._execution_model.latency_offsets,
                        intent=intent,
                        remaining_quantity=intent.quantity,
                    )
                )

            next_pending: list[_PendingOrder] = []
            for order in pending:
                if order.ready_offset > event.event_offset:
                    next_pending.append(order)
                    continue

                outcome = self._try_partial_fill(order, event)
                if isinstance(outcome, RejectedIntent):
                    rejected.append(outcome)
                    continue

                if outcome is None:
                    # Fill probability miss: retain the live remainder so a
                    # later event may fill it. This is intentionally different
                    # from V3.73's one-shot full-fill semantics.
                    next_pending.append(order)
                    continue

                fill, filled_quantity = outcome
                fills.append(fill)
                self._apply_fill(ledger, fill, order.intent.side)
                order.remaining_quantity -= filled_quantity
                order.fill_index += 1
                assert_finite(float(order.remaining_quantity))

                if order.remaining_quantity > 0:
                    # A single market event contributes at most one partial
                    # execution for a given order. The remainder becomes
                    # eligible on the next event.
                    order.ready_offset = event.event_offset + 1
                    next_pending.append(order)

            pending = next_pending
            equity = ledger.equity(event.close)
            assert_finite(float(equity))
            equity_curve.append(equity)

        open_orders = tuple(
            sorted(
                ((order.intent.intent_id, order.remaining_quantity) for order in pending),
                key=lambda item: item[0],
            )
        )
        final_equity = equity_curve[-1] if equity_curve else ledger.cash
        state = {
            "symbol": self._symbol,
            "execution_model_version": self._execution_model.version,
            "mode": self._execution_model.mode.value,
            "participation_rate": str(self._execution_model.participation_rate),
            "fills": [
                {
                    "fill_id": fill.fill_id,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                }
                for fill in fills
            ],
            "rejected": [
                {
                    "intent_id": item.intent_id,
                    "offset": item.event_offset,
                    "reason": item.reason.value,
                }
                for item in rejected
            ],
            "open_orders": [(intent_id, str(quantity)) for intent_id, quantity in open_orders],
            "final_equity": str(final_equity),
            "event_count": len(market_events),
        }
        return PartialFillBacktestResult(
            fills=tuple(fills),
            rejected_intents=tuple(rejected),
            open_orders=open_orders,
            equity_curve=tuple(equity_curve),
            final_equity=final_equity,
            final_quantity=ledger.quantity,
            event_count=len(market_events),
            state_hash=canonical_hash(state),
            execution_model_version=self._execution_model.version,
            mode=self._execution_model.mode,
        )

    def _try_partial_fill(
        self, order: _PendingOrder, event: MarketEvent
    ) -> tuple[Fill, Decimal] | RejectedIntent | None:
        intent = order.intent
        if intent.symbol != event.symbol:
            return RejectedIntent(intent.intent_id, event.event_offset, RejectionReason.SYMBOL_MISMATCH)
        try:
            intent.validate(event.event_time)
        except ValueError:
            return RejectedIntent(
                intent.intent_id,
                event.event_offset,
                PartialFillRejectionReason.WINDOW_EXPIRED,
            )

        if self._execution_model.fill_probability < Decimal("1"):
            digest = hashlib.sha256(
                f"{self._seed}:{event.event_offset}:{intent.intent_id}:{order.fill_index}".encode()
            ).hexdigest()
            draw = Decimal(int(digest[:8], 16)) / Decimal(0xFFFFFFFF)
            if draw > self._execution_model.fill_probability:
                return None

        max_fillable = event.volume * self._execution_model.participation_rate
        filled_quantity = min(order.remaining_quantity, max_fillable)
        if filled_quantity <= 0:
            return None

        base_price = event.close
        slip = base_price * self._execution_model.slippage_bps / Decimal("10000")
        exec_price = base_price + slip if intent.side == Side.BUY else base_price - slip
        fee = exec_price * filled_quantity * self._execution_model.fee_bps / Decimal("10000")
        assert_finite(float(exec_price), float(fee), float(filled_quantity))

        fill = Fill(
            fill_id=f"PF-{event.event_offset}-{intent.intent_id}-{order.fill_index}",
            order_request_id=intent.intent_id,
            exchange_order_id=f"SIM-PF-{event.event_offset}-{intent.intent_id}",
            quantity=filled_quantity,
            price=exec_price,
            fee=fee,
            slippage=slip,
            event_time=event.event_time,
            trade_id=f"TRADE-PF-{event.event_offset}-{intent.intent_id}-{order.fill_index}",
            venue="BACKTEST_PARTIAL_FILL_SIM",
        )
        return fill, filled_quantity

    @staticmethod
    def _apply_fill(ledger: _Ledger, fill: Fill, side: Side) -> None:
        notional = fill.price * fill.quantity
        if side == Side.BUY:
            ledger.cash -= notional
            ledger.quantity += fill.quantity
        else:
            ledger.cash += notional
            ledger.quantity -= fill.quantity
        ledger.cash -= fill.fee
        assert_finite(float(ledger.cash), float(ledger.quantity))

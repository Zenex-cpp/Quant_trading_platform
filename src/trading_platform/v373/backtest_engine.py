"""V3.73 — Backtest Engine (§84 BACKTEST ENGINE).

Deterministically replays the full causal chain over an ordered sequence of
market events:

    Market -> Feature -> Regime -> Prediction -> Signal -> Opportunity ->
    Portfolio -> Risk -> Intent -> Execution -> Fill -> Position ->
    Accounting -> P&L

Design choices and why:

- Each pipeline stage (feature/regime/prediction/signal/opportunity/
  portfolio/risk/intent) is an injected pure callable, not logic owned by
  this engine. The engine's only job is deterministic sequencing, execution
  simulation, and ledger bookkeeping. This is intentional: a future live
  runner can inject the *same* callables, which is a precondition for
  §85 BACKTEST/LIVE PARITY -- but this module does not itself implement a
  live runner, so parity is NOT proven here, only made possible.
- Order intents are the real `trading_platform.execution.models.OrderIntent`
  contract (not a parallel ad hoc shape), so TTL/window expiry (§20),
  causal IDs (§21), and the existing validation rules are enforced exactly
  as they would be live. An intent whose window has already expired as of
  the bar it would fill on is rejected, not silently used -- this is the
  same causality invariant required by §22, applied inside the backtest.
- Money fields are Decimal throughout, matching the rest of the codebase.
- `ExecutionModelConfig` is a versioned, explicit cost/latency/fill-
  probability model (§86), not implicit constants.
- `SimulationMode` distinguishes IDEALIZED (no slippage/latency/rejection
  beyond what's configured) from REALISTIC (non-zero slippage/latency/fill
  probability expected) per §87. STRESS mode is declared but not yet
  implemented -- see scope boundary below.
- `DeterminismClass` (§89) must be declared per execution-model config and
  is validated against the fill-probability setting: a non-certain fill
  probability can only ever be STOCHASTIC_BUT_SEEDED, and seeding is via a
  SHA-256 digest of (seed, event_offset) -- never wall-clock entropy -- so
  re-running the same inputs always reproduces the same fills.
- The final state hash reuses the existing `replay.canonical_hash`, so a
  backtest run participates in the same reproducibility proof mechanism as
  the rest of the platform rather than inventing a second one (§88 partial).

Explicit scope boundary (what this module does NOT close):
- §85 BACKTEST/LIVE PARITY: not proven; no live runner exists yet to share
  these callables with.
- §87 SIMULATION MODES: STRESS mode is declared as an enum value only; no
  adverse-liquidity/rejection-shock behavior is implemented for it yet.
- §86 EXECUTION MODEL: covers fee, slippage, latency-as-offset-count, and
  fill probability. Does not model order-book depth, partial fills, or
  venue-specific rejection codes.
- §88 REPLAY ENGINE: covers full-run determinism (two full runs of the same
  inputs match). Does not implement resume-from-arbitrary-offset / partial
  snapshot restore.
- OrderIntent.action (OPEN/INCREASE/DECREASE/CLOSE/NO_ACTION) is passed
  through but not yet used to change fill/sizing semantics beyond "fill the
  requested signed quantity in the requested side." Position netting rules
  that depend on action are future work.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional, Sequence

from trading_platform.core.nonfinite import assert_finite
from trading_platform.execution.models import Fill, OrderIntent, Side
from trading_platform.replay.replay import canonical_hash


class SimulationMode(str, Enum):
    IDEALIZED = "IDEALIZED"
    REALISTIC = "REALISTIC"
    STRESS = "STRESS"


class DeterminismClass(str, Enum):
    EXACT = "EXACT"
    TOLERANCE_EQUIVALENT = "TOLERANCE_EQUIVALENT"
    STOCHASTIC_BUT_SEEDED = "STOCHASTIC_BUT_SEEDED"


class RejectionReason(str, Enum):
    WINDOW_EXPIRED_OR_NOT_YET_VALID = "WINDOW_EXPIRED_OR_NOT_YET_VALID"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    FILL_PROBABILITY_MISS = "FILL_PROBABILITY_MISS"


class OutOfOrderEventError(ValueError):
    """Raised when market events are not supplied in strictly increasing
    event_offset order. The engine never reorders events itself -- ordering
    is an upstream contract (§28 EVENT ORDERING), not something this engine
    guesses at."""


@dataclass(frozen=True)
class MarketEvent:
    event_offset: int
    event_time: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None:
            raise ValueError("EVENT_TIME_MUST_BE_TIMEZONE_AWARE")
        if self.event_offset < 0:
            raise ValueError("INVALID_EVENT_OFFSET")
        for value in (self.open, self.high, self.low, self.close, self.volume):
            assert_finite(float(value))
        if self.volume < 0:
            raise ValueError("INVALID_VOLUME")
        if self.high < self.low:
            raise ValueError("INVALID_OHLC_RANGE")
        if not (self.low <= self.open <= self.high) or not (self.low <= self.close <= self.high):
            raise ValueError("INVALID_OHLC_RANGE")


@dataclass(frozen=True)
class ExecutionModelConfig:
    """§86 EXECUTION MODEL."""

    version: str
    mode: SimulationMode
    fee_bps: Decimal
    slippage_bps: Decimal
    determinism: DeterminismClass
    latency_offsets: int = 0
    fill_probability: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("EXECUTION_MODEL_VERSION_REQUIRED")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("INVALID_COST_PARAMETER")
        if self.latency_offsets < 0:
            raise ValueError("INVALID_LATENCY_OFFSET")
        if not (Decimal("0") <= self.fill_probability <= Decimal("1")):
            raise ValueError("INVALID_FILL_PROBABILITY")
        certain = self.fill_probability == Decimal("1")
        if certain and self.determinism == DeterminismClass.STOCHASTIC_BUT_SEEDED:
            raise ValueError("DETERMINISM_CLASS_MISMATCH")
        if not certain and self.determinism != DeterminismClass.STOCHASTIC_BUT_SEEDED:
            raise ValueError("DETERMINISM_CLASS_MISMATCH")


@dataclass(frozen=True)
class BacktestStageFunctions:
    """Pluggable, pure callables for each causal-chain stage (§84/§21).
    Supplying the same callables to a future live runner is the mechanism
    by which §85 parity could eventually be demonstrated; this dataclass
    only defines the shared seam, it does not create the live side."""

    feature_fn: Callable
    regime_fn: Callable
    prediction_fn: Callable
    signal_fn: Callable
    opportunity_fn: Callable
    portfolio_fn: Callable
    risk_fn: Callable
    intent_fn: Callable  # -> Optional[OrderIntent]


@dataclass
class _PositionLedger:
    quantity: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")

    def equity(self, mark_price: Decimal) -> Decimal:
        return self.cash + self.quantity * mark_price


@dataclass(frozen=True)
class RejectedIntent:
    intent_id: str
    event_offset: int
    reason: RejectionReason


@dataclass(frozen=True)
class BacktestResult:
    fills: tuple[Fill, ...]
    rejected_intents: tuple[RejectedIntent, ...]
    equity_curve: tuple[Decimal, ...]
    final_equity: Decimal
    final_quantity: Decimal
    event_count: int
    state_hash: str
    execution_model_version: str
    mode: SimulationMode


class BacktestEngine:
    """§84 BACKTEST ENGINE. See module docstring for scope boundary."""

    def __init__(
        self,
        stages: BacktestStageFunctions,
        execution_model: ExecutionModelConfig,
        symbol: str,
        seed: int = 0,
    ) -> None:
        self._stages = stages
        self._execution_model = execution_model
        self._symbol = symbol
        self._seed = seed

    def run(self, market_events: Sequence[MarketEvent]) -> BacktestResult:
        ledger = _PositionLedger()
        fills: list[Fill] = []
        rejected: list[RejectedIntent] = []
        equity_curve: list[Decimal] = []
        last_offset = -1
        pending: list[tuple[int, OrderIntent]] = []

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
                ready_offset = event.event_offset + self._execution_model.latency_offsets
                pending.append((ready_offset, intent))

            still_pending: list[tuple[int, OrderIntent]] = []
            for ready_offset, pending_intent in pending:
                if ready_offset <= event.event_offset:
                    outcome = self._try_fill(pending_intent, event)
                    if isinstance(outcome, Fill):
                        fills.append(outcome)
                        self._apply_fill(ledger, outcome, pending_intent.side)
                    else:
                        rejected.append(outcome)
                else:
                    still_pending.append((ready_offset, pending_intent))
            pending = still_pending

            equity = ledger.equity(event.close)
            assert_finite(float(equity))
            equity_curve.append(equity)

        final_equity = equity_curve[-1] if equity_curve else ledger.cash
        state = {
            "symbol": self._symbol,
            "execution_model_version": self._execution_model.version,
            "mode": self._execution_model.mode.value,
            "fills": [
                {
                    "fill_id": f.fill_id,
                    "quantity": str(f.quantity),
                    "price": str(f.price),
                    "fee": str(f.fee),
                }
                for f in fills
            ],
            "rejected": [
                {"intent_id": r.intent_id, "offset": r.event_offset, "reason": r.reason.value}
                for r in rejected
            ],
            "final_equity": str(final_equity),
            "event_count": len(market_events),
        }
        return BacktestResult(
            fills=tuple(fills),
            rejected_intents=tuple(rejected),
            equity_curve=tuple(equity_curve),
            final_equity=final_equity,
            final_quantity=ledger.quantity,
            event_count=len(market_events),
            state_hash=canonical_hash(state),
            execution_model_version=self._execution_model.version,
            mode=self._execution_model.mode,
        )

    def _try_fill(self, intent: OrderIntent, event: MarketEvent):
        if intent.symbol != event.symbol:
            return RejectedIntent(intent.intent_id, event.event_offset, RejectionReason.SYMBOL_MISMATCH)

        try:
            intent.validate(event.event_time)
        except ValueError:
            return RejectedIntent(
                intent.intent_id, event.event_offset, RejectionReason.WINDOW_EXPIRED_OR_NOT_YET_VALID
            )

        if self._execution_model.fill_probability < Decimal("1"):
            digest = hashlib.sha256(f"{self._seed}:{event.event_offset}".encode()).hexdigest()
            draw = Decimal(int(digest[:8], 16)) / Decimal(0xFFFFFFFF)
            if draw > self._execution_model.fill_probability:
                return RejectedIntent(
                    intent.intent_id, event.event_offset, RejectionReason.FILL_PROBABILITY_MISS
                )

        base_price = event.close
        slip = base_price * self._execution_model.slippage_bps / Decimal("10000")
        exec_price = base_price + slip if intent.side == Side.BUY else base_price - slip
        fee = exec_price * intent.quantity * self._execution_model.fee_bps / Decimal("10000")
        assert_finite(float(exec_price), float(fee))

        return Fill(
            fill_id=f"BT-{event.event_offset}-{intent.intent_id}",
            order_request_id=intent.intent_id,
            exchange_order_id=f"SIM-{event.event_offset}",
            quantity=intent.quantity,
            price=exec_price,
            fee=fee,
            slippage=slip,
            event_time=event.event_time,
            venue="BACKTEST_SIM",
        )

    @staticmethod
    def _apply_fill(ledger: _PositionLedger, fill: Fill, side: Side) -> None:
        notional = fill.price * fill.quantity
        if side == Side.BUY:
            ledger.cash -= notional
            ledger.quantity += fill.quantity
        else:
            ledger.cash += notional
            ledger.quantity -= fill.quantity
        ledger.cash -= fill.fee
        assert_finite(float(ledger.cash), float(ledger.quantity))

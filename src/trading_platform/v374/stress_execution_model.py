"""V3.74 — STRESS simulation mode for the Backtest Engine (§87 SIMULATION MODES).

V3.73 implemented IDEALIZED and REALISTIC and declared STRESS as an enum
value with no behavior. This module implements STRESS: adverse-liquidity
rejection, outright stress rejection, and amplified slippage, each a
separate, independently seeded, explicitly declared assumption per §87
("Ogni mode definisce: assumptions; costs; latency; fills; liquidity;
rejection; stochasticity; seed").

Why this is a new module rather than an edit to v373/backtest_engine.py:
this repository's convention (every prior version, e.g. v371 importing from
v369) is that a shipped version's files are not edited by a later version --
later versions add new files that import and extend them. Editing V3.73 in
place would also silently change the already-published
V373_BACKTEST_ENGINE_EVIDENCE.json's meaning after the fact, which the
platform's own evidence-immutability principle (§172) rules out.

How this extends V3.73 rather than duplicating it:
- `StressExecutionModelConfig` subclasses `ExecutionModelConfig` structurally
  (reusing its fields), but fully replaces `__post_init__` rather than
  calling `super().__post_init__()`. Reason: V3.73's determinism check
  considers only `fill_probability`, so under this module's additional
  `rejection_probability` stochastic source, a config with
  `fill_probability=1` and `rejection_probability=0.3` must be
  `STOCHASTIC_BUT_SEEDED`, which V3.73's own rule would incorrectly reject
  (it would conclude "certain fill_probability => must not be
  STOCHASTIC_BUT_SEEDED"). Calling the parent check would therefore block
  valid stress configs, so this module supersedes it instead, documented
  here rather than silently diverging.
- `StressBacktestEngine` subclasses `BacktestEngine` and overrides only
  `_try_fill`; `run()` is inherited unchanged and dispatches to the override
  polymorphically. The override adds liquidity-cap and stress-rejection
  checks ahead of the base fill-probability check (via an explicit call to
  `super()._try_fill(...)`), then applies the slippage multiplier to
  whatever Fill the base method produces.

Known residual gap (disclosed, not fixed here): nothing in V3.73 stops a
caller from constructing a plain (non-Stress) `ExecutionModelConfig` with
`mode=SimulationMode.STRESS` and running it through the plain
`BacktestEngine`. That combination is accepted but applies no adverse
behavior at all -- it behaves exactly like REALISTIC despite claiming to be
STRESS. Closing this requires a guard in V3.73's `BacktestEngine.__init__`
that rejects `mode=STRESS` outright, which this module cannot add without
editing V3.73. This is recorded as an open item in
`compliance_v374.csv`, not silently left undocumented.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from trading_platform.core.nonfinite import assert_finite
from trading_platform.execution.models import Fill, Side
from trading_platform.v373.backtest_engine import (
    BacktestEngine,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    RejectedIntent,
    SimulationMode,
)


class StressRejectionReason(str, Enum):
    STRESS_REJECTED = "STRESS_REJECTED"
    LIQUIDITY_CAP_EXCEEDED = "LIQUIDITY_CAP_EXCEEDED"


@dataclass(frozen=True)
class StressExecutionModelConfig(ExecutionModelConfig):
    rejection_probability: Decimal = Decimal("0")
    liquidity_participation_cap: Optional[Decimal] = None
    stress_slippage_multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:  # intentionally does not call super(); see module docstring
        if not self.version:
            raise ValueError("EXECUTION_MODEL_VERSION_REQUIRED")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("INVALID_COST_PARAMETER")
        if self.latency_offsets < 0:
            raise ValueError("INVALID_LATENCY_OFFSET")
        if not (Decimal("0") <= self.fill_probability <= Decimal("1")):
            raise ValueError("INVALID_FILL_PROBABILITY")
        if self.mode != SimulationMode.STRESS:
            raise ValueError("STRESS_EXECUTION_MODEL_REQUIRES_STRESS_MODE")
        if not (Decimal("0") <= self.rejection_probability <= Decimal("1")):
            raise ValueError("INVALID_REJECTION_PROBABILITY")
        if self.liquidity_participation_cap is not None and not (
            Decimal("0") < self.liquidity_participation_cap <= Decimal("1")
        ):
            raise ValueError("INVALID_LIQUIDITY_PARTICIPATION_CAP")
        if self.stress_slippage_multiplier < Decimal("1"):
            raise ValueError("INVALID_STRESS_SLIPPAGE_MULTIPLIER")

        adverse_configured = (
            self.rejection_probability > Decimal("0")
            or self.liquidity_participation_cap is not None
            or self.stress_slippage_multiplier > Decimal("1")
        )
        if not adverse_configured:
            raise ValueError("STRESS_MODE_REQUIRES_AT_LEAST_ONE_ADVERSE_PARAMETER")

        stochastic_needed = self.fill_probability < Decimal("1") or self.rejection_probability > Decimal("0")
        if stochastic_needed and self.determinism != DeterminismClass.STOCHASTIC_BUT_SEEDED:
            raise ValueError("DETERMINISM_CLASS_MISMATCH")
        if not stochastic_needed and self.determinism == DeterminismClass.STOCHASTIC_BUT_SEEDED:
            raise ValueError("DETERMINISM_CLASS_MISMATCH")


class StressBacktestEngine(BacktestEngine):
    """§87 STRESS mode runner. Requires a `StressExecutionModelConfig`."""

    def __init__(self, stages, execution_model: StressExecutionModelConfig, symbol: str, seed: int = 0) -> None:
        if not isinstance(execution_model, StressExecutionModelConfig):
            raise ValueError("STRESS_ENGINE_REQUIRES_STRESS_EXECUTION_MODEL")
        super().__init__(stages, execution_model, symbol, seed)

    def _seeded_draw(self, event_offset: int, namespace: str) -> Decimal:
        digest = hashlib.sha256(f"{self._seed}:{event_offset}:{namespace}".encode()).hexdigest()
        return Decimal(int(digest[:8], 16)) / Decimal(0xFFFFFFFF)

    def _try_fill(self, intent, event: MarketEvent):
        model: StressExecutionModelConfig = self._execution_model  # type: ignore[assignment]

        if model.liquidity_participation_cap is not None:
            max_fillable = event.volume * model.liquidity_participation_cap
            if intent.quantity > max_fillable:
                return RejectedIntent(
                    intent.intent_id, event.event_offset, StressRejectionReason.LIQUIDITY_CAP_EXCEEDED
                )

        if model.rejection_probability > Decimal("0"):
            if self._seeded_draw(event.event_offset, "stress_rejection") < model.rejection_probability:
                return RejectedIntent(
                    intent.intent_id, event.event_offset, StressRejectionReason.STRESS_REJECTED
                )

        outcome = super()._try_fill(intent, event)
        if not isinstance(outcome, Fill):
            return outcome

        if model.stress_slippage_multiplier > Decimal("1"):
            base_slip = event.close * model.slippage_bps / Decimal("10000")
            extra_slip = base_slip * (model.stress_slippage_multiplier - Decimal("1"))
            direction = Decimal("1") if intent.side == Side.BUY else Decimal("-1")
            adjusted_price = outcome.price + direction * extra_slip
            adjusted_fee = adjusted_price * outcome.quantity * model.fee_bps / Decimal("10000")
            assert_finite(float(adjusted_price), float(adjusted_fee))
            outcome = Fill(
                fill_id=outcome.fill_id,
                order_request_id=outcome.order_request_id,
                exchange_order_id=outcome.exchange_order_id,
                quantity=outcome.quantity,
                price=adjusted_price,
                fee=adjusted_fee,
                funding=outcome.funding,
                slippage=outcome.slippage + extra_slip,
                market_impact=outcome.market_impact,
                event_time=outcome.event_time,
                trade_id=outcome.trade_id,
                venue=outcome.venue,
            )
        return outcome

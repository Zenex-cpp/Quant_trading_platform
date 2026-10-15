#!/usr/bin/env python3
"""V3.74 STRESS-mode drill: proves the three adverse mechanisms (liquidity
cap, stress rejection, slippage multiplier) each behave as declared, and
that the STOCHASTIC_BUT_SEEDED path is seeded (same seed reproduces,
different seed is free to diverge) rather than wall-clock random.

INTERNAL, REPOSITORY_RELEASE_ARTIFACT evidence. Does not prove production
readiness; see evidence_boundary below.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    DeterminismClass,
    MarketEvent,
    SimulationMode,
)
from trading_platform.v374.stress_execution_model import (
    StressBacktestEngine,
    StressExecutionModelConfig,
    StressRejectionReason,
)

SYMBOL = "BTCUSDT"


def _events(n: int, volume: str = "10"):
    out = []
    for i in range(n):
        price = Decimal(100 + (i % 5))
        out.append(
            MarketEvent(
                event_offset=i,
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
                symbol=SYMBOL,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Decimal(volume),
            )
        )
    return out


def _wide_window() -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _buy_every_bar(quantity: str = "1") -> BacktestStageFunctions:
    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id=f"I-{event.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="DRILL-V374",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal(quantity),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    return BacktestStageFunctions(
        feature_fn=lambda event: None,
        regime_fn=lambda event, feature: None,
        prediction_fn=lambda event, feature, regime: None,
        signal_fn=lambda event, prediction: None,
        opportunity_fn=lambda event, signal, regime: None,
        portfolio_fn=lambda event, opportunity, qty: None,
        risk_fn=lambda event, decision, qty: None,
        intent_fn=intent_fn,
    )


def check_liquidity_cap() -> dict:
    model = StressExecutionModelConfig(
        version="DRILL-LIQ",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        liquidity_participation_cap=Decimal("0.2"),
    )
    events = _events(5, volume="10")  # cap = 2 units/bar
    result = StressBacktestEngine(_buy_every_bar(quantity="4"), model, SYMBOL).run(events)
    all_capped = all(r.reason is StressRejectionReason.LIQUIDITY_CAP_EXCEEDED for r in result.rejected_intents)
    return {
        "check": "liquidity_participation_cap",
        "requested_per_bar": "4",
        "cap_per_bar": "2",
        "fills": len(result.fills),
        "rejections": len(result.rejected_intents),
        "all_rejections_are_liquidity_cap": all_capped,
        "pass": len(result.fills) == 0 and all_capped and len(result.rejected_intents) == len(events),
    }


def check_stress_rejection_seeded() -> dict:
    model = StressExecutionModelConfig(
        version="DRILL-REJ",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.STOCHASTIC_BUT_SEEDED,
        rejection_probability=Decimal("0.4"),
    )
    events = _events(40)
    r1 = StressBacktestEngine(_buy_every_bar(), model, SYMBOL, seed=21).run(events)
    r2 = StressBacktestEngine(_buy_every_bar(), model, SYMBOL, seed=21).run(events)
    r3 = StressBacktestEngine(_buy_every_bar(), model, SYMBOL, seed=22).run(events)
    same_seed_matches = r1.state_hash == r2.state_hash
    different_seed_diverges = r1.state_hash != r3.state_hash
    not_vacuous = 0 < len(r1.fills) < len(events)
    return {
        "check": "stress_rejection_probability_seeded",
        "seed_21_run_1_hash": r1.state_hash,
        "seed_21_run_2_hash": r2.state_hash,
        "seed_22_run_hash": r3.state_hash,
        "seed_21_fill_count": len(r1.fills),
        "event_count": len(events),
        "same_seed_reproducible": same_seed_matches,
        "different_seed_free_to_diverge": different_seed_diverges,
        "not_vacuous_mix_of_fills_and_rejections": not_vacuous,
        "pass": same_seed_matches and different_seed_diverges and not_vacuous,
    }


def check_slippage_multiplier_monotonic() -> dict:
    results = {}
    prior_price = None
    monotonic = True
    for mult in ["1", "2", "5"]:
        model = StressExecutionModelConfig(
            version=f"DRILL-SLIP-{mult}",
            mode=SimulationMode.STRESS,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("10"),
            determinism=DeterminismClass.EXACT,
            stress_slippage_multiplier=Decimal(mult),
        ) if mult != "1" else StressExecutionModelConfig(
            version="DRILL-SLIP-1",
            mode=SimulationMode.STRESS,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("10"),
            determinism=DeterminismClass.EXACT,
            liquidity_participation_cap=Decimal("1"),  # satisfy "at least one adverse param" without adding slippage
        )
        result = StressBacktestEngine(_buy_every_bar(), model, SYMBOL).run(_events(1))
        price = result.fills[0].price
        results[f"multiplier_{mult}"] = str(price)
        if prior_price is not None and not (price >= prior_price):
            monotonic = False
        prior_price = price
    return {
        "check": "slippage_multiplier_monotonic_with_price_paid",
        "prices_by_multiplier": results,
        "pass": monotonic,
    }


def main() -> None:
    checks = [check_liquidity_cap(), check_stress_rejection_seeded(), check_slippage_multiplier_monotonic()]
    overall_pass = all(c["pass"] for c in checks)
    report = {
        "schema_version": "V374_STRESS_EXECUTION_MODEL_1",
        "scope": "APPLICATION_BACKTEST_STRESS_MODE",
        "source_kind": "INTERNAL",
        "checks": checks,
        "status": "PASS" if overall_pass else "FAIL",
        "production_ready": False,
        "evidence_boundary": [
            "Proves the three stress mechanisms behave as declared and are seeded, not that they are calibrated to any real market's adverse conditions.",
            "Does not close \u00a785 backtest/live parity.",
            "Does not model order-book depth or partial fills; liquidity cap rejects the whole order rather than partially filling it.",
            "A plain ExecutionModelConfig with mode=STRESS run through the base BacktestEngine is still silently accepted with no adverse behavior -- see V374 release notes.",
        ],
    }
    payload = json.dumps(report, indent=2, sort_keys=True)
    report["evidence_hash"] = sha256(payload.encode()).hexdigest()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

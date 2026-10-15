#!/usr/bin/env python3
"""V3.73 backtest-engine determinism drill.

Runs two scenarios against the real BacktestEngine and records whether the
observed behavior matches the determinism class declared for each
ExecutionModelConfig:

  1. EXACT scenario (fill_probability=1): two runs of identical inputs must
     produce an identical state_hash and an identical fill sequence.
  2. STOCHASTIC_BUT_SEEDED scenario (fill_probability=0.5): two runs with the
     SAME seed must match exactly; a run with a DIFFERENT seed is free to
     diverge (and, over 30 bars at p=0.5, is checked to actually diverge, so
     this isn't a vacuously-true check).

This is INTERNAL, REPOSITORY_RELEASE_ARTIFACT evidence: it proves the engine
behaves deterministically under the stated rules. It does not prove
backtest/live parity (§85), does not implement STRESS mode (§87), and does
not model order-book depth, partial fills, or venue rejection codes (§86).
`production_ready` is FALSE; this drill does not change that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import (
    BacktestEngine,
    BacktestStageFunctions,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    SimulationMode,
)

SYMBOL = "BTCUSDT"


def _events(n: int):
    out = []
    for i in range(n):
        price = Decimal(100 + (i % 7))
        out.append(
            MarketEvent(
                event_offset=i,
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
                symbol=SYMBOL,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Decimal("10"),
            )
        )
    return out


def _wide_window() -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _buy_every_bar_stages() -> BacktestStageFunctions:
    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id=f"I-{event.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="DRILL",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    noop = lambda *a, **k: None
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


def run_exact_determinism_check() -> dict:
    model = ExecutionModelConfig(
        version="DRILL-EXACT",
        mode=SimulationMode.IDEALIZED,
        fee_bps=Decimal("2"),
        slippage_bps=Decimal("1"),
        determinism=DeterminismClass.EXACT,
    )
    events = _events(15)
    r1 = BacktestEngine(_buy_every_bar_stages(), model, SYMBOL).run(events)
    r2 = BacktestEngine(_buy_every_bar_stages(), model, SYMBOL).run(events)
    matched = r1.state_hash == r2.state_hash and [f.fill_id for f in r1.fills] == [
        f.fill_id for f in r2.fills
    ]
    return {
        "scenario": "EXACT",
        "declared_class": model.determinism.value,
        "run_1_state_hash": r1.state_hash,
        "run_2_state_hash": r2.state_hash,
        "fill_count": len(r1.fills),
        "matched": matched,
    }


def run_stochastic_but_seeded_check() -> dict:
    model = ExecutionModelConfig(
        version="DRILL-STOCHASTIC",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.STOCHASTIC_BUT_SEEDED,
        fill_probability=Decimal("0.5"),
    )
    events = _events(30)
    r_seed_a1 = BacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=7).run(events)
    r_seed_a2 = BacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=7).run(events)
    r_seed_b = BacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=11).run(events)

    same_seed_matches = r_seed_a1.state_hash == r_seed_a2.state_hash
    different_seed_diverges = r_seed_a1.state_hash != r_seed_b.state_hash
    not_vacuous = 0 < len(r_seed_a1.fills) < len(events)

    return {
        "scenario": "STOCHASTIC_BUT_SEEDED",
        "declared_class": model.determinism.value,
        "seed_7_run_1_hash": r_seed_a1.state_hash,
        "seed_7_run_2_hash": r_seed_a2.state_hash,
        "seed_11_run_hash": r_seed_b.state_hash,
        "seed_7_fill_count": len(r_seed_a1.fills),
        "event_count": len(events),
        "same_seed_reproducible": same_seed_matches,
        "different_seed_free_to_diverge": different_seed_diverges,
        "not_vacuous_mix_of_fills_and_misses": not_vacuous,
    }


def main() -> None:
    exact = run_exact_determinism_check()
    stochastic = run_stochastic_but_seeded_check()
    overall_pass = (
        exact["matched"]
        and stochastic["same_seed_reproducible"]
        and stochastic["not_vacuous_mix_of_fills_and_misses"]
    )
    report = {
        "schema_version": "V373_BACKTEST_ENGINE_DETERMINISM_1",
        "scope": "APPLICATION_BACKTEST_ENGINE_DETERMINISM",
        "source_kind": "INTERNAL",
        "exact_scenario": exact,
        "stochastic_but_seeded_scenario": stochastic,
        "status": "PASS" if overall_pass else "FAIL",
        "production_ready": False,
        "evidence_boundary": [
            "Does not prove backtest/live parity (\u00a785): no live runner exists yet to share these stage callables with.",
            "Does not implement STRESS simulation mode (\u00a787).",
            "Execution model covers fee, slippage, latency-as-offset-count, and fill probability only (\u00a786); no order-book depth, partial fills, or venue rejection codes.",
            "Covers full-run determinism only (\u00a788); no resume-from-offset / partial snapshot restore.",
        ],
    }
    payload = json.dumps(report, indent=2, sort_keys=True)
    report["evidence_hash"] = sha256(payload.encode()).hexdigest()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

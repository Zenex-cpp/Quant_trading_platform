# V3.74 Release Notes

## Scope
V3.74 adds `src/trading_platform/v374/stress_execution_model.py`:
**STRESS simulation mode** for the Backtest Engine, closing a boundary V3.73
explicitly left open (STRESS was declared as a `SimulationMode` enum value
but had no behavior).

## What's new
- `StressExecutionModelConfig` — adds `rejection_probability` (independent
  stress-only rejection draw), `liquidity_participation_cap` (reject orders
  larger than a configured fraction of the bar's volume), and
  `stress_slippage_multiplier` (amplifies base slippage). Requires
  `mode=STRESS` and at least one of the three adverse parameters set —
  a STRESS config that configures nothing adverse is rejected at
  construction, so "STRESS" can't silently mean "REALISTIC."
- `StressBacktestEngine` — subclasses V3.73's `BacktestEngine`, overriding
  only `_try_fill`; `run()` is inherited unchanged. Liquidity-cap and
  stress-rejection checks run first (their own seeded draw, independent of
  the base fill-probability draw), then delegates to the base method, then
  applies the slippage multiplier to whatever Fill comes back.

## Master Prompt alignment
- §87 SIMULATION MODES: STRESS is now implemented (liquidity, rejection,
  and stochasticity/seed are all explicit and declared per the config, as
  required).
- §89 DETERMINISM CONTRACT: the stress-only stochastic source
  (`rejection_probability`) is validated against `determinism` the same way
  V3.73 validates `fill_probability` — but see "why a new module" below for
  why this couldn't just call V3.73's existing check.

## Why this is a new module, not an edit to V3.73
This repository's established convention is that a shipped version's files
are not edited later — later versions import and extend them (e.g. V3.71
imports from V3.69). Editing `v373/backtest_engine.py` in place would also
retroactively change what `V373_BACKTEST_ENGINE_EVIDENCE.json` was evidence
*for*, which conflicts with the evidence-immutability principle (§172) the
rest of this platform already follows. So V3.74 adds new files and reuses
V3.73's types (`ExecutionModelConfig`, `BacktestEngine`, `MarketEvent`,
`RejectedIntent`) rather than duplicating them.

One consequence: `StressExecutionModelConfig.__post_init__` does **not**
call `super().__post_init__()`. V3.73's determinism check only knows about
`fill_probability`; under a config with `fill_probability=1` but
`rejection_probability=0.3`, V3.73's rule would incorrectly demand
`EXACT` when `STOCHASTIC_BUT_SEEDED` is actually correct. V3.74 fully
replaces the validation (duplicating ~6 lines of V3.73's bounds-checking)
rather than inheriting a check that would reject valid stress configs.

## Known residual gap (disclosed, not fixed)
Nothing in V3.73 stops a caller from building a **plain**
`ExecutionModelConfig` with `mode=SimulationMode.STRESS` and running it
through the **base** `BacktestEngine`. That combination is accepted but
applies zero adverse behavior — it runs exactly like REALISTIC while
claiming to be STRESS. Only `StressExecutionModelConfig` +
`StressBacktestEngine` together implement real stress semantics. Properly
closing this needs a guard inside V3.73's `BacktestEngine.__init__`
rejecting `mode=STRESS` outright, which V3.74 cannot add without editing
V3.73. Tracked as an open item in `compliance_v374.csv`.

## What this does NOT close
- §85 BACKTEST/LIVE PARITY — unchanged from V3.73, still open.
- §86 — still no order-book depth or true partial fills; the liquidity cap
  rejects the whole order rather than filling part of it.
- The base-engine/STRESS-mode foot-gun above.

`production_ready` remains `FALSE`.

## Verification
- Full automated suite: **700/700 PASS** (691 pre-existing + 9 new; zero
  regressions).
- Stress-mode drill (`run_v374_stress_determinism.py`): **PASS** — see
  `V374_STRESS_EXECUTION_MODEL_EVIDENCE.json`.

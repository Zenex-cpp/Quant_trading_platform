# V3.73 Release Notes

## Scope
V3.73 adds `src/trading_platform/v373/backtest_engine.py`: a deterministic,
event-driven **Backtest Engine** implementing the causal chain Market ->
Feature -> Regime -> Prediction -> Signal -> Opportunity -> Portfolio ->
Risk -> Intent -> Execution -> Fill -> Position -> Accounting -> P&L.

This is the first backtest engine in the repository. Prior versions (V1-V372)
built governance, state-machine, risk, accounting, and evidence
infrastructure, but nothing that actually replays historical data through a
strategy to produce fills and P&L — which Mission section 1 ("formulare e
falsificare hypothesis", "confrontare modelli e strategie") depends on.

## Master Prompt alignment
- §84 BACKTEST ENGINE: implemented — event-driven replay of the full chain
  above, with pluggable per-stage callables.
- §86 EXECUTION MODEL: implemented — versioned `ExecutionModelConfig` with
  fee, slippage, latency (as event-offset count), and fill probability.
- §87 SIMULATION MODES: partially implemented — `IDEALIZED` and `REALISTIC`
  are usable; `STRESS` is declared as an enum value only, with no behavior.
- §89 DETERMINISM CONTRACT: implemented and enforced — every
  `ExecutionModelConfig` must declare `EXACT` or `STOCHASTIC_BUT_SEEDED`,
  validated against its own `fill_probability`; the stochastic path is
  seeded from `(seed, event_offset)` via SHA-256, never wall-clock entropy.
- §88 REPLAY ENGINE: partially covered — full-run determinism (two runs,
  identical state_hash) is proven via the existing `replay.canonical_hash`.
  Resume from an arbitrary offset is not implemented.
- §20 / §21 / §22 (TTL, causal chain, causality invariant): order intents
  use the real `OrderIntent` / `ValidWindow` contracts from
  `execution.models` and `core.ttl`, not a parallel shape. An intent whose
  window has already expired as of the bar it would fill on is rejected,
  not used — enforcing the same causality rule inside the backtest that the
  live system is required to enforce.

## What this does NOT close
- §85 BACKTEST/LIVE PARITY: not proven. No live runner exists yet to invoke
  the same `BacktestStageFunctions`, which is the precondition for parity.
- §87 STRESS mode: not implemented.
- §86: no order-book depth, partial fills, or venue-specific rejection
  codes.
- §88: no incremental snapshot/resume.
- `OrderIntent.action` (OPEN/INCREASE/DECREASE/CLOSE) is accepted but not
  yet used to change sizing/netting behavior.

`production_ready` remains `FALSE`.

## Verification
- Full automated suite: **691/691 PASS** (680 pre-existing + 11 new).
- Determinism drill (`run_v373_backtest_determinism.py`): **PASS** — see
  `V373_BACKTEST_ENGINE_EVIDENCE.json`.

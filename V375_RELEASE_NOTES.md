# V3.75 Release Notes

## Scope

V3.75 adds a machine-checkable **decision-stage backtest/live parity contract**
for §85. It introduces a decision-only live/shadow runner that consumes the
same `BacktestStageFunctions` used by the backtest engine, plus deterministic
stage traces and a comparator.

## What's new

- `LiveDecisionEngine` executes the shared decision chain:
  `Feature -> Regime -> Prediction -> Signal -> Opportunity -> Portfolio -> Risk -> Intent`.
- `BacktestDecisionTraceCollector` records the same stage outputs from the
  existing V3.73 backtest without modifying V3.73.
- `DecisionTrace` hashes each stage output using a typed canonical
  representation and produces one deterministic trace hash.
- `compare_decision_traces()` returns a machine-checkable PASS/FAIL result and
  mismatch offsets.
- The live/shadow runner has no exchange transport and therefore cannot create
  an order side effect.

## Master Prompt alignment

§85 requires the live path to share the decision engines with the backtest
path while changing mainly data/execution/environment boundaries. V3.75
implements and verifies the **shared decision seam** without falsely claiming
full live parity.

The verification therefore uses an explicit narrower requirement:

`S85 = VERIFIED` for decision-stage parity.

Full operational parity remains open until the project has a live/shadow market
data adapter plus common execution/accounting/reconciliation integration.

## Verification

- New V3.75 test suite: 6 functional checks covering equality, deterministic
  hashing, mutation detection, input validation, and no execution side effects.
- A generated evidence artifact compares a backtest trace and a live/shadow
  trace on the same four-bar BTCUSDT event sequence and records identical
  trace hashes.
- A deliberate risk-stage mutation produces a parity failure on all affected
  offsets, proving the comparator is not vacuous.

## Open gaps carried forward

- §85 full operational backtest/live parity: OPEN.
- §86 order-book depth, true partial fills, and venue-specific execution
  semantics: OPEN.
- §87 platform-wide STRESS-mode enforcement: OPEN; legacy V3.73 base engine
  remains frozen and can still accept a plain `ExecutionModelConfig(mode=STRESS)`.
- §88 checkpoint/resume replay: OPEN.
- `production_ready = FALSE`.

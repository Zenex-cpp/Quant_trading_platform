# V3.76 Release Notes

## Scope

V3.76 closes the specific §86 execution-model gap left by V3.74: liquidity
participation is now capable of producing **deterministic partial fills**
rather than only all-or-nothing rejection.

## What's new

- `PartialFillExecutionModelConfig` adds an explicit `participation_rate`.
- `PartialFillBacktestEngine` reuses the V3.73 decision-stage contract while
  allowing an eligible intent to remain pending after a partial fill.
- Each event can produce at most one fill for an order; the remainder becomes
  eligible on the next event.
- Remainders are never silently treated as filled: they are either completed,
  rejected on expiry, or reported in `open_orders` at end-of-data.
- Seeded stochastic fill probability remains deterministic and is incorporated
  into the partial-fill attempt identity.

## Master Prompt alignment

§86 requires explicit execution-model assumptions and realistic treatment of
fills. V3.76 proves the execution layer can represent more than full-fill vs
reject under a bar-volume participation constraint.

§89 determinism is preserved: the same inputs and seed produce the same fill
sequence and state hash.

## Verification

- 7 new tests cover multi-bar partial fills, no-overfill, end-of-data open
  remainder, expiry path, seeded reproducibility, and model-type enforcement.
- Evidence runner proves 2 + 2 + 1 units fill from a 5-unit intent against a
  20% participation rate over three 10-unit bars, with identical replay hash.

## Open gaps carried forward

- §85 full operational backtest/live parity: OPEN.
- §86 order-book depth, queue position, maker/taker semantics, and
  venue-specific execution semantics: OPEN.
- §87 platform-wide STRESS-mode enforcement: OPEN; legacy V3.73 base engine
  remains frozen and can still accept a plain `ExecutionModelConfig(mode=STRESS)`.
- §88 checkpoint/resume replay: OPEN.
- `production_ready = FALSE`.

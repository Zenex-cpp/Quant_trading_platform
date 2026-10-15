# V3.76 Verification Report

## Change scope

Adds `src/trading_platform/v376/partial_fill_execution.py`, its package export,
`tests/test_v376_partial_fill_execution.py`, and the deterministic evidence
runner `run_v376_partial_fill.py`.

## Verification

- Full automated suite: 713/713 PASS (706 pre-existing + 7 new; zero regressions).
- 5-unit intent under 20% participation and 10-unit bars produces fills of
  exactly 2, 2, and 1 units across successive events — PASS.
- Filled quantity cannot exceed requested quantity; completed order leaves no
  open remainder — PASS.
- End-of-data before completion leaves the exact unfilled remainder visible in
  `open_orders` — PASS.
- Identical seeded stochastic runs reproduce the same state hash and fills — PASS.
- Plain V3.73 `ExecutionModelConfig` is rejected by the partial-fill engine — PASS.
- STRESS mode is rejected by the partial-fill model because it lacks the V3.74 stress contract — PASS.

## Evidence boundary

`V376_PARTIAL_FILL_EXECUTION_EVIDENCE.json` proves the deterministic partial-fill
mechanics of the new engine under an explicit participation-rate assumption.
It does not prove order-book depth, queue position, venue matching, latency
parity, accounting/reconciliation parity, or production readiness.

`production_ready = FALSE`.

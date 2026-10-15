# V3.77 Release Notes

## Scope

V3.77 addresses the §88 checkpoint/resume gap for the current v3.x partial-fill
backtest path without modifying historical releases.

## What's new

- Immutable `BacktestCheckpoint` with canonical state hash.
- Snapshot of the mutable execution state, including pending orders and their
  `fill_index`, so a partial-fill order resumes without replaying the prefix.
- Exact event-boundary enforcement through `next_event_offset`.
- Compatibility guards for snapshot version, execution model, mode, symbol and
  seed.
- Tamper detection and fail-closed resume behavior.
- Immutable research/test checkpoint store rejecting identifier reuse.
- Evidence runner proving full replay and resumed replay are state-equivalent.

## Master Prompt alignment

§88 requires replay reconstruction with an explicit event offset, snapshot
version and state hash. V3.77 makes those fields part of a machine-verifiable
checkpoint artifact and proves causal continuation after the checkpoint.

§11 and §29 idempotency/integrity principles are respected by rejecting
checkpoint identifier reuse and refusing to resume from a tampered artifact.

## Open gaps carried forward

- §85 full operational backtest/live parity: OPEN.
- §86 order-book depth, queue position, maker/taker semantics, and
  venue-specific execution semantics: OPEN.
- §87 platform-wide STRESS-mode enforcement: OPEN; legacy V3.73 base engine
  remains frozen and can still accept a plain `ExecutionModelConfig(mode=STRESS)`.
- §88 production-durable cross-process/live checkpointing and full-platform
  checkpoint coverage: OPEN.
- `production_ready = FALSE`.

# V4.29 follow-up — PIT split and end-to-end acceptance

## Purpose

Correct two gaps found while checking the current implementation against Master Prompt v5.0 §§93, 95, 177, and 178:

1. The chronological splitter previously purged training labels at the train/validation boundary only. Validation and OOS label intervals could reach the following split, including the final holdout.
2. The V3.58 acceptance runner reported recovery and rollback as `PASS` without reopening the persisted fill/accounting state or exercising deployment rollback, and the gate did not require those proof artifacts.
3. The §178 chain lacked distinct `Validation` and `Model` stages and combined `Accounting` with `P&L`, so its stage manifest did not match the prompt's specified transitions.

## Changes

- `chronological_split` now requires event timestamps alongside label end times, purges label overlap at all three temporal boundaries, applies configured embargoes between all adjacent splits, and rejects malformed or emptied splits.
- The acceptance runner constructs targets only for non-purged training indices. It processes OOS observations in timestamp order and stops at the first crossing of the fixed signal threshold; prediction no longer depends on target-label artifacts.
- Risk decisions, order intents, fill identity, and accounting state are reopened from SQLite. Duplicate fills are ignored, conflicting fill content is rejected, expired risk is rejected, and accounting state is reconstructed and checked with a recovery proof.
- The runner invokes the deployment rollback drill and requires failure-injection, recovery, and rollback artifacts in both the evidence snapshot and the acceptance gate.
- The stage manifest now records `Historical Data → Validation → Feature → Target → Baseline → Model → Prediction` explicitly, with separate `Accounting` and `P&L` artifacts. Features stop at OOS and final-holdout targets remain unconstructed.
- The `Position` artifact is derived from the durable fill and checked against the SQLite accounting projection before P&L is calculated.
- Validation, feature, target, baseline, model and prediction hashes are included in the replay state; the full stage-hash set is bound into the evidence snapshot, and the gate requires the validation and model artifacts alongside recovery, failure-injection and rollback evidence.
- The result identifies its environment as `OFFLINE_SIMULATION`; it keeps `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.
- The same acceptance flow can now be run outside pytest from a source checkout with `python scripts/run_offline_acceptance.py`, or after installation with `trading-platform offline-acceptance` / `python -m trading_platform offline-acceptance`. It prints the evidence report as JSON and has a regression that rejects any socket connection attempt.

## Requirements and evidence

| Requirement | Status | Evidence |
|---|---|---|
| §93/§95 target-window purge and holdout boundary | TESTED | `tests/test_v03_completion.py` |
| M2 expired RiskDecision fails closed after restart | TESTED | `tests/test_v358_e2e_acceptance.py` |
| §178 deterministic offline pipeline, failure injection, recovery, rollback | TESTED | `tests/test_v358_e2e_acceptance.py`; `V368_ROLLBACK_EXERCISE` |
| M27 holdout incident invalidates dependent evidence after interruption/restart | TESTED | `tests/v354/test_m27_holdout_compromise.py`; `V429_M27_REMEDIATION_REPORT.md` |

These are application-level tests over synthetic data and local SQLite files. They are not independent review, exchange evidence, or production-readiness evidence. No live or Testnet order is sent.

## Validation

- Focused splitter and end-to-end acceptance tests: **17 passed** on Windows/Python 3.14.7.
- Mandatory full V4.29 runner on Windows/Python 3.14.7: **1,163 passed, 26 skipped**, `RELEASE_HYGIENE=PASS` (decision `V429-SPLIT-PURGE-20261104-02`).
- PR #11 merged as `e0d6611`; its hosted validation and the subsequent `main` push run completed successfully at **1,187 passed, 2 skipped**, `RELEASE_HYGIENE=PASS`. That run predates the separate M27 restart-recovery follow-up and does not validate its new test.
- Historical CLI runtime verification on package `3.61.10` produced a 22-stage report with hash `06da7827ff1c7453583ebdeeb238f44bdc915f242de1952e4651fed275176772`; that manifest omitted the separate Validation/Model/P&L stages now required by §178.
- On package `3.61.28`, the focused E2E regression passed **3 tests**. `python scripts/run_offline_acceptance.py` emitted a deterministic JSON report with **25 stage artifacts**, the exact ordered 22-stage §178 chain plus failure-injection/recovery/rollback, and report hash `c8fc20a7fb2e800ed68cfc3c50a43e7a448fb020415356b87cc5b4b5100d4904`. The acceptance and gate pass in `OFFLINE_SIMULATION`; `external_evidence=false`, `production_ready=false` and `activation_flag=NOT_SET`.
- Mandatory full V4.29 runner on package `3.61.28`: **1,353 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight `.audit/V428_MILESTONE_PREFLIGHT.json` is `READY_FOR_MILESTONE`, `allowed=true`, zero blockers and 170 input hashes.

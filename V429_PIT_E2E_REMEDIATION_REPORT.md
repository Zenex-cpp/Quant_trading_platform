# V4.29 follow-up — PIT split and end-to-end acceptance

## Purpose

Correct two gaps found while checking the current implementation against Master Prompt v5.0 §§93, 95, 177, and 178:

1. The chronological splitter previously purged training labels at the train/validation boundary only. Validation and OOS label intervals could reach the following split, including the final holdout.
2. The V3.58 acceptance runner reported recovery and rollback as `PASS` without reopening the persisted fill/accounting state or exercising deployment rollback, and the gate did not require those proof artifacts.

## Changes

- `chronological_split` now requires event timestamps alongside label end times, purges label overlap at all three temporal boundaries, applies configured embargoes between all adjacent splits, and rejects malformed or emptied splits.
- The acceptance runner constructs targets only for non-purged training indices. It processes OOS observations in timestamp order and stops at the first crossing of the fixed signal threshold; prediction no longer depends on target-label artifacts.
- Risk decisions, order intents, fill identity, and accounting state are reopened from SQLite. Duplicate fills are ignored, conflicting fill content is rejected, expired risk is rejected, and accounting state is reconstructed and checked with a recovery proof.
- The runner invokes the deployment rollback drill and requires failure-injection, recovery, and rollback artifacts in both the evidence snapshot and the acceptance gate.
- The result identifies its environment as `OFFLINE_SIMULATION`; it keeps `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.

## Requirements and evidence

| Requirement | Status | Evidence |
|---|---|---|
| §93/§95 target-window purge and holdout boundary | TESTED | `tests/test_v03_completion.py` |
| M2 expired RiskDecision fails closed after restart | TESTED | `tests/test_v358_e2e_acceptance.py` |
| §178 deterministic offline pipeline, failure injection, recovery, rollback | TESTED | `tests/test_v358_e2e_acceptance.py`; `V368_ROLLBACK_EXERCISE` |
| M27 holdout incident invalidates all dependent evidence | PARTIAL | This change avoids holdout target access in the acceptance path; automated incident-to-evidence invalidation remains incomplete. |

These are application-level tests over synthetic data and local SQLite files. They are not independent review, exchange evidence, or production-readiness evidence. No live or Testnet order is sent.

## Validation

- Focused splitter and end-to-end acceptance tests: **17 passed** on Windows/Python 3.14.7.
- Mandatory full V4.29 runner on Windows/Python 3.14.7: **1,163 passed, 26 skipped**, `RELEASE_HYGIENE=PASS` (decision `V429-SPLIT-PURGE-20261104-02`).
- Hosted PR and post-merge CI results are pending; this report does not treat local simulation as external evidence.

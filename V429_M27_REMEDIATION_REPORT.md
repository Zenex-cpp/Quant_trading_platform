# V4.29 follow-up — restart-safe Final Holdout invalidation

## Finding

M27 already rejected unauthorized tuning access and durably invalidated dependent evidence, gates, candidates, and promotions during the same process. The access context did not replay a durable `FINAL_HOLDOUT_COMPROMISED` incident when rebuilt, however. A process stop after recording the compromise and before writing the dependency invalidation could leave dependents without the invalidation record after restart.

## Change

- `HoldoutCompromiseAuthorityLedger.reconcile_compromises()` replays each hash-chained compromise event through the idempotent dependency invalidation ledger, then repairs the durable per-evidence audit events.
- `HoldoutAccessContext.build()` completes that reconciliation before returning a usable context. Invalid chain or inconsistent replay errors fail closed and prevent context construction.
- A SQLite restart test records the compromise, closes the store before invalidation, reopens it, and verifies that evidence, gates, candidates, and promotions are invalidated before the recovered context can be used.
- The V4.29 matrix now points to the current M27 code, tests, and report and records `TESTED`. Independent reviewer approval and external operational audit evidence remain open, so M27 is not `VERIFIED`.

## Verification

- Focused holdout, snapshot, and V4.29 matrix tests: **18 passed** on Windows.
- Mandatory V4.29 runner on Windows/Python 3.14.7: **1,165 passed, 26 skipped**; `RELEASE_HYGIENE=PASS` (decision `V429-M27-RESTART-20261105-03`).
- Hosted `main` validation of the preceding PR #11 merge (`e0d6611`): **1,187 passed, 2 skipped**; `RELEASE_HYGIENE=PASS` (run [42023395397](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/42023395397)). That hosted run predates this M27 follow-up; this follow-up still requires its own PR validation.

## Boundary

This is local SQLite and synthetic evidence testing. It does not provide independent reviewer approval, external evidence, authenticated Testnet execution, or production operations evidence. `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain in force.

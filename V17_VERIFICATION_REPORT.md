# V1.7 Verification Report

## Offline regression

Base V1.5 suite plus V1.7 safety/workflow tests: **130 passed**.

## Plan-only CLI

`python scripts/run_v17_testnet.py --plan-only` completed successfully and reported `TESTNET`, `mutations_enabled=false`, and `production_ready=false`.

## Live Testnet read-only probe

The opt-in read-only probe was executed against the configured Testnet endpoint. Both TN-01 and TN-02 returned `FAIL` in this environment, and the failure was persisted as durable evidence. No mutation was attempted and no credentials were used.

This is **not** treated as live exchange success evidence. Production readiness remains false.

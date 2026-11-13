# V4.29 M23 Dynamic Drawdown Source Binding

**Status:** `TESTED`; independent history attestation and production accounting integration remain open.

## Finding

The drawdown factor was available as a caller-supplied scalar and was not derived from a durable portfolio-equity history. That left the dynamic budget detached from the accounting records and did not bind history completeness, current-source freshness, or the historical peak to the runtime and restart-safe risk decisions.

## Changes

- `DrawdownHistoryLedger` now stores hash-chained accounting snapshots and requires an explicit opening snapshot, nonempty history-evidence ID and `verified=True` before observations or assessments are accepted.
- Later snapshots must have unique IDs and strictly increasing timestamps. Assessment replay computes the peak only from the declared opening anchor through the current snapshot and binds the current/peak snapshot hashes, history evidence ID, history fingerprint and freshness window.
- Runtime authority requires the current snapshot hash to appear in accounting Operational Truth, derives the drawdown value from the assessment and rejects raw scalar-only drawdown.
- The existing conservative drawdown cap remains monotone: higher drawdown cannot increase allowed risk. The assessment fingerprint is bound into the order route, one-shot capability and durable decision record; changed and expired sources fail closed on validation/replay.
- M23 is included in the fixed V4.29 runner, compliance matrix and CI workflow contract.

## Verification boundary

The focused M23/authority/durable/workflow/release-contract set passed **70 tests** on Windows/Python 3.14.4. The mandatory full V4.29 runner on package 3.61.18 passed with **1,314 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; `.audit/V429_M23_DRAWDOWN_FINAL_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers and M23 in the impacted set.

Tests use synthetic `AccountingSnapshot` records and a caller-provided evidence ID. The `verified=True` argument is not a signature, independent source attestation, or proof that the opening balance is complete. No live portfolio accounting integration or independent review is available in this checkout. M23 therefore remains `TESTED`, not `VERIFIED`; no production or trading activation is implied.

`external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

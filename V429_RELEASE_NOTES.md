# Trading Platform V4.29 Recovery — Release Notes

## Summary

V4.29 hardens the independent Ed25519 signer against symlinked ancestor paths, input-file replacement during reads, unbounded external evidence inputs, and accidental overwrite of a pre-existing signed output. It also creates a V4.29-specific mandatory milestone runner and CI workflow contract.

Python package 3.61.11 adds a bounded importer for Binance USD-M Futures daily kline archives, verifies the official SHA-256 sidecars, validates/normalizes rows, and writes immutable snapshots with raw archive lineage and a dataset quality manifest. It adds a separate exact-host public-data egress zone while keeping Research deny-all. The command requires an explicit non-commercial research attestation because the reviewed Binance Vision terms exclude live proprietary/commercial trading and paid signal distribution. M25 remains TESTED pending infrastructure route evidence. No real dataset is downloaded by tests.

Python package 3.61.12 adds a bounded, local-only `market-data audit-csv` path for DATASET-01. It records a DatasetContract and quality/coverage report when a user/vendor CSV has complete timezone-aware coverage. The report explicitly leaves source-license review and independent source comparison unresolved; no user market-data CSV is present in the checkout, so no real dataset was audited.

On package 3.61.12, the Windows/Python 3.14.7 focused CSV/CLI/release-integrity set passed **15 tests**; the mandatory full V4.29 runner passed with **1,262 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. Preflight was `READY_FOR_MILESTONE`, `allowed=true`, and had no blocking reasons. All audit fixtures are synthetic; this does not close DATASET-01 source comparison or production-readiness gates.

Python package 3.61.13 adds optional local comparison of two OHLCV CSVs for DATASET-01. The command creates a contract for each source with complete timestamps, normalizes join keys to UTC event time and uppercase symbol, records coverage differences and per-field OHLCV discrepancies, and supports bounded absolute/relative tolerances. A match does not prove source independence or licensing; no real user CSVs are present.

On package 3.61.13, the focused CSV/CLI/release-integrity set passed **22 tests**; the mandatory full V4.29 runner passed with **1,269 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. Preflight was `READY_FOR_MILESTONE`, `allowed=true`, with no blocking reasons. A push-triggered hosted run for commit `30ba40e` passed as run [43042509186](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43042509186) and uploaded artifact `V428-validation-audit-43042509186-1`; the artifact archive digest is recorded in `compliance_v429.csv`. The run was on the working branch, not protected `main`.

On package 3.61.11, the Windows/Python 3.14.7 mandatory V4.29 runner passed with **1,255 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, with M9, M14 and M25 impacted and no blocking reasons. The focused market-data, segmentation, workflow-contract, matrix and release-integrity suite passed **43 tests**. GitHub hosted CI has not run for this local patch.

Python package `3.61.5` makes the final dispatcher require current risk, position, market-data, and causal-TTL authorities before a new risk-increasing order can reach its gateway. The runtime now passes the durable RiskDecision ledger, and V4.29 CI preflights M1–M5 for this boundary. See `V429_M2_REMEDIATION_REPORT.md`.

Python package `3.61.6` closes alternate Testnet submit paths through the V3.36/V3.79/V3.80/V3.84/V3.85 adapters. The V3.85 controlled submit shares the final M1–M5 authority checks; older direct-submit adapters fail closed. See `V429_M1_M5_TRANSPORT_REMEDIATION.md`.

Python package `3.61.7` closes the M7 Champion gate-claim gap. Promotion now requires durable PASS gate authorizations and binds each authorization to the exact gate run and fingerprint, which are checked again at promotion and LIVE activation. The V4.29 preflight now includes M7 in the impacted-control set. See `V429_M7_REMEDIATION_REPORT.md`.

Python package `3.61.8` guards the V3.75 live/shadow prediction callable with a durable M14 compatibility authorization, checks the current seven-dimension report on every call, and includes M14 in the V4.29 preflight and CI contract. It does not add a production inference adapter. See `V429_M14_REMEDIATION_REPORT.md`.

Python package `3.61.9` closes M9 research-boundary gaps for credential-bearing `__slots__` objects and NumPy object arrays, and validates direct tuning-data views. The V4.29 preflight and CI contract now include M9. The credential vault remains an in-process recovery implementation pending production credential-store and process-isolation evidence. See `V429_M9_REMEDIATION_REPORT.md`.

Python package `3.61.10` adds an installed command-line entry point and a source-checkout runner (`python scripts/run_offline_acceptance.py`) for the complete §178 offline acceptance chain. It emits the deterministic JSON report and uses synthetic data plus local SQLite only; a test blocks socket connections during command execution.

On package `3.61.10`, the Windows/Python 3.14.7 mandatory runner passed with **1,242 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, with M9 and M14 impacted and no blocking reasons. The source-checkout CLI also completed the 22-stage §178 flow as `OFFLINE_SIMULATION`, with `production_ready=false` and `activation_flag=NOT_SET`.

On package `3.61.8`, the Windows/Python 3.14.7 mandatory runner passed with **1,224 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE` with M14 impacted and no blocking reasons.

On package `3.61.9`, the Windows/Python 3.14.7 mandatory runner passed with **1,240 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, with M9 and M14 impacted and no blocking reasons. Pytest now explicitly collects the retained legacy credential test module so its regressions run in the mandatory suite. Hosted CI has not yet run for the local M14/M9 changes because GitHub access is unavailable in this environment.

At package `3.61.5`, the mandatory Windows/Python 3.14.7 runner completed with **1,190 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. On package `3.61.6`, it completed with **1,200 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. On the current `3.61.7` tree, it completed with **1,201 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`, preflight `READY_FOR_MILESTONE`. These local results do not replace hosted CI or external review.

## Verification contract

- Full regression runs through `scripts/run_milestone_validation_v429.py`.
- CI invokes the same fixed-command runner and requires the governance audit artifact set to be present.
- V4.28 governance snapshot schema and two preflight artifact names are retained solely for compatibility; this does not establish remote evidence.
- `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain unchanged.

## Provenance

Direct baseline: `trading_platform_v4_28_recovery.tar.gz`, SHA-256 `c04b3584d9c5de21bd57c22f491895101da5fb7f3d5d99c034a9b77c5f8b09a4`.
Canonical continuity to V4.23/V4.26 is `NOT_ESTABLISHED` due unavailable original archives.

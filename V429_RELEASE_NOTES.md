# Trading Platform V4.29 Recovery — Release Notes

## Summary

V4.29 hardens the independent Ed25519 signer against symlinked ancestor paths, input-file replacement during reads, unbounded external evidence inputs, and accidental overwrite of a pre-existing signed output. It also creates a V4.29-specific mandatory milestone runner and CI workflow contract.

Python package 3.61.21 closes an M21 trust gap: signed manifest `calibration_state` is metadata only and cannot lift the conservative cap. Live assessment requires a separately computed calibration report; absent or invalid report forces `UNKNOWN`. The report fingerprint, source IDs, sample sizes, scores, drift and threshold-derived state are bound into the uncertainty assessment and flow through runtime authority, router, capability, durable decision and final dispatch. This fingerprint is not a digital signature and does not authenticate the dataset or producer. M21 remains `TESTED` pending real-data ablation, market-specific thresholds and independent source/reviewer evidence.

On package 3.61.21, the focused M21/model/calibration/M22/M23/durable regression passed **90 tests**. The mandatory full V4.29 runner passed with **1,337 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. `.audit/V429_M21_FINAL3_20261112.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers, M21 included and 161 contract-input hashes. Fixture reports are synthetic and unsigned; this is local software verification, not independent calibration or production approval.

Python package 3.61.19 adds an order-book liquidity assessment that binds depth utilization, spread and estimated VWAP impact to a fresh market-data record and exact order through risk authority, capabilities, durable decisions and final dispatch. The focused M22/M23/dispatch and matrix/workflow/release-contract set passed **63 tests**. The mandatory full V4.29 runner passed with **1,322 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, with M22 included and no blockers. Evidence uses synthetic books; M22 remains `TESTED` while authenticated live feeds, real-market calibration and independent review are pending.

Python package 3.61.17 binds model-health evidence identity and freshness through runtime authority, one-shot capabilities, and durable risk decisions. Changed source fingerprints and evidence that expires before commit or risk revalidation fail closed. The focused M24 and release-contract set passed **51 tests**; the mandatory full V4.29 runner passed **1,307 tests, 26 skipped**, with `RELEASE_HYGIENE=PASS`. Preflight `.audit/V429_M24_SOURCE_BINDING_FINAL3_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers, and M24 included. The synthetic `verified` flag does not prove a signed trusted source; independent source attestation and production integration remain open.

Python package 3.61.18 closes the M23 integration gap by deriving drawdown from a durable, hash-chained accounting-equity history with an explicit opening snapshot and history-evidence ID. The source assessment is bound through runtime authority, order routing, one-shot capabilities and durable risk decisions; stale, changed, uninitialized or scalar-only sources fail closed. The focused M23/authority/durable/workflow/release-contract set passed **70 tests**. The mandatory full V4.29 runner passed with **1,314 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; `.audit/V429_M23_DRAWDOWN_FINAL_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers, and M23 included. The bootstrap `verified` flag remains a caller assertion, so independent history authentication and production accounting integration remain open.

Python package 3.61.16 replaces implicit in-memory Production credential storage with an explicit persistent backend contract and Windows Credential Manager implementation. The vault persists only metadata/fingerprints in the event ledger, restores lifecycle state on restart, checks fetched credential fingerprints and deletes revoked entries. Deployment still needs a dedicated production service identity and independent process-isolation evidence.

Python package 3.61.14 validates both decision traces before allowing a backtest/live parity result to pass. Empty traces, unsupported versions, mutable record containers, duplicate or reordered event offsets, malformed offsets and content-hash mismatches fail closed with explicit validation errors. The record comparison preserves duplicate offsets. Focused decision, execution-parity, release-integrity and release-hygiene regressions passed **30 tests** on Windows/Python 3.14.7. Production inference, external review and operational readiness remain open.

Python package 3.61.15 adds a bounded Ed25519-signed JSON model loader. It validates exact artifact hash, schemas, model/feature/target versions and runtime/dependency/configuration compatibility before parsing coefficients. The live M14 boundary binds the loaded model ID and hash to its durable authorization. Synthetic-key tests cover tampering and compatibility failures; reviewer trust-root governance and production deployment remain open. The full test and preflight result is recorded below after local validation.

The mandatory full Windows/Python 3.14.7 V4.29 runner on package 3.61.15 passed with **1,291 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight `READY_FOR_MILESTONE`, `allowed=true`, with M14/M15 included and no blockers. Audit report: `.audit/V429_M15_FINAL3_PREFLIGHT_20261111.json`. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

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

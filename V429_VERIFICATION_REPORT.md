# V4.29 Recovery — Verification Report

## Current package — 3.61.43

Package 3.61.43 adds `PersistentTransitionEngine` for the single registered `START_BACKTEST` transition. The engine persists the current orthogonal state, idempotency record, and audit event in one SQLite transaction, recovers exact retries after restart, rejects changed specifications and stale source states, and serializes concurrent writers. A trigger-injected audit failure verifies all records roll back together. Caller callbacks and external side effects are deliberately unsupported. The focused state-transition and release checks passed **19 tests**. The full V4.29 runner passed on Windows/Python 3.14.7 with **1,441 passed, 26 skipped**, exit code 0, and `RELEASE_HYGIENE=PASS`. Preflight: `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, 265 unique input hashes, zero blockers; `external_evidence=false`, `production_ready=false`, `activation_flag=NOT_SET`. Hosted CI for code head `d6201e0e67b2ffeebf55ee9b14187615aabb9c97` passed in [run 44360777245](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/44360777245) with **1,464 passed, 3 skipped**, `RELEASE_HYGIENE=PASS`; artifact 14455665032 has SHA-256 `196d519d597c491105d2d8a8f81fab1781d54ea20d7717b57bb1f12024e220bb` (34,412 bytes). Governance remains BLOCKED by missing trusted governance evidence.

FD-06 remains `PARTIAL`: the named system-lifecycle and risk-state machines still have no approved positive paths, and external side-effect recovery is not implemented.

## Package 3.61.42

Package 3.61.42 binds EventStore event-ID retries to the persisted canonical event hash over timestamp, type, aggregate, and payload. Exact retries return the prior record; changed content raises `EVENT_APPEND_CONFLICT`. Regression tests cover each field and confirm the original event and chain remain unchanged after rejection. The stable attestation timestamp also keeps V3.96 retries byte-for-byte idempotent after a process restart. Focused EventStore, concurrency, V3.96 attestation, and release checks passed **29 tests**. The full V4.29 runner passed on Windows/Python 3.14.7 with **1,435 passed, 26 skipped**, exit code 0, and `RELEASE_HYGIENE=PASS`. Preflight: `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, 265 unique input hashes, zero blockers; `external_evidence=false`, `production_ready=false`, `activation_flag=NOT_SET`. Hosted CI on code head `097a698efa8e3b324e6cd092160f312be1e604da` passed in [run 44357344871](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/44357344871) with **1,458 passed, 3 skipped**, `RELEASE_HYGIENE=PASS`; artifact 14452657119 has SHA-256 `9b7975f994bf67229196893681fb6ee6e37ba280a24d3b00a6216cfd2ef7da17` (34,393 bytes).

## Package 3.61.41

Package 3.61.41 adds a deterministic §28 batch-ordering function and an in-memory per-source stream guard. It canonicalizes simultaneous events without claiming cross-source causality, rejects late/out-of-order stream input, and requires replay after a conflict. Focused event-ordering, schema-registry, and release-version checks passed **21 tests**. The fixed local V4.29 runner passed on Windows/Python 3.14.7 with **1,431 passed, 26 skipped**, exit 0, and `RELEASE_HYGIENE=PASS`. Preflight: `READY_FOR_MILESTONE`, `allowed=true`, 262 unique hashes, zero blockers; `external_evidence=false`, `production_ready=false`, `activation_flag=NOT_SET`. Durable cursor persistence and platform-wide event registry integration remain unverified.

## Package 3.61.40

Package 3.61.40 adds ordered monotonicity checks for execution-risk position-size caps and concentration-adjusted correlated-exposure caps. `adjusted_risk` applies the normalized execution-risk input, validates factor bounds, and rejects conflicting overrides. Focused monotonicity/release checks passed 19 tests. The fixed V4.29 runner passed on Windows/Python 3.14.7 with **1,423 passed, 26 skipped**, exit 0, and `RELEASE_HYGIENE=PASS`. Preflight: `READY_FOR_MILESTONE`, `allowed=true`, 258 unique input hashes, zero blockers; `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`. No external evidence, production authorization, or live trading is implied.

FD-08 remains PARTIAL because the measurements remain caller-supplied, correlation modeling and provenance are not established, and immutable platform-wide ceiling binding is not proven.

## Package 3.61.39

The §179 register now contains 55 unique deliverables: 50 PRESENT, 5 PARTIAL, and 0 OPEN. New canonical contracts cover FD-21, FD-24, FD-25, FD-29, FD-41, FD-53, and FD-54. The causal chain validator checks dependency IDs and recursively validates ancestry, state, timestamps, provenance, and expiry. Risk-state helpers apply state factors to caller-supplied ceilings; gate validation checks transitive prerequisites and their required artifacts. The statistical-method catalog also records prompt-listed methods without implementations as specification-only.

The fixed local V4.29 runner passed on Windows/Python 3.14.7 with **1,417 passed, 26 skipped**, exit code 0, and `RELEASE_HYGIENE=PASS`. Preflight: `READY_FOR_MILESTONE`, `allowed=true`, 257 unique contract-input hashes, zero blockers. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`. Hosted PR CI run 44348438800 passed for head `66195a5d0323649723e91cb37f344f06ac87ea97`; its audit artifact is ID 14447910723 with SHA-256 `e8ab94b3d16e22e0057faf6f97030b12fb0760c380c3daac7e3b7c3b1b21e23a`.

The remaining §179 PARTIAL entries are FD-06, FD-08, FD-10/FD-11, and FD-44. The statistical method specification rows for Deflated Sharpe, PBO, bootstrap, permutation, and multiple-testing correction explicitly state that implementations are absent. No exchange order, deployment, or production activation was performed.

## V5.0 §179 first-delivery traceability

Package 3.61.30 adds a 55-row register mapped to the exact prompt deliverables. Automated contract tests require unique ordered IDs, valid repository paths, and a stated gap for each PARTIAL or OPEN entry. The Model Card and Strategy Card templates are documented; StrategyCard is immutable and fingerprints all canonical fields. The six previously OPEN safety and research items now have versioned machine-readable registries. Transition idempotency rejects a conflicting spec before changing state. Focused first-delivery validation passed 35 tests; transition, release-version, and runner-contract validation passed 34. The full V4.29 runner passed with 1,363 passed, 26 skipped, and RELEASE_HYGIENE=PASS. Its preflight is READY_FOR_MILESTONE, allowed=true, pipeline PASS, zero blockers and 188 input hashes; the local activation boundary remains external_evidence=false, production_ready=false, and activation_flag=NOT_SET.

**Disposition:** `READY_FOR_MILESTONE`; `external_evidence=false`; `production_ready=false`.

## Parent and provenance

Parent archive: `trading_platform_v4_28_recovery.tar.gz`.
Parent SHA-256: `c04b3584d9c5de21bd57c22f491895101da5fb7f3d5d99c034a9b77c5f8b09a4`.

This is a recovery extension built from the exact V4.28 recovery archive present in the runtime. Byte-for-byte canonical lineage to the unavailable V4.23 and V4.26 source archives remains `NOT_ESTABLISHED`.

## Change summary

- The independent signer reads the reviewer private key and unsigned provider evidence through POSIX directory file descriptors with `O_NOFOLLOW` on path components.
- The private-key file is bounded to 1 MiB; the evidence file is bounded to 16 MiB. Both must be regular files outside the checkout, with no symlinked path components.
- File metadata is checked before and after reads to reject detected replacement or mutation during the read.
- Signed output is created as a new file using exclusive creation, no-follow opens and mode `0600`; existing files are never overwritten.
- Unsupported platforms without the strict path primitives fail closed.
- A V4.29-specific workflow contract and mandatory milestone runner use `compliance_v429.csv` and the exact V4.28 parent archive digest.
- V4.28 governance payload schema and audit artifact names are retained for compatibility with the existing provider capture normalizer.
- M23 derives risk drawdown from an explicitly initialized accounting-equity history and binds the complete history fingerprint through runtime, capability and durable decision gates.

## Verification results

- Latest local package 3.61.28 validation on Windows/Python 3.14.7: **1,353 passed, 26 skipped**, mandatory runner exit code 0, RELEASE_HYGIENE=PASS.
- Focused §178 stage-contract tests: **3 passed**. The offline CLI emits 25 stage artifacts, containing the exact ordered 22-stage prompt chain plus failure injection, recovery and rollback; report hash `c8fc20a7fb2e800ed68cfc3c50a43e7a448fb020415356b87cc5b4b5100d4904`.
- Focused M14/model/parity/release regression: **53 passed**. A loaded model is the only accepted signed-model runtime object; direct construction, dataclass copies and duck-typed metadata fail before prediction, and oversized numeric conversion returns a bounded model error.
- `.audit/V428_MILESTONE_PREFLIGHT.json`: `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, `release_hygiene=PASS`, zero blockers and **170 contract-input hashes**.
- Focused Python 3.10 syntax/M21/release-integrity/hygiene coverage: **28 passed**. The syntax test checks every src/ and scripts/ Python file with the minimum-version grammar plus a same-quote f-string regression.
- `.audit/V429_PY310_COMPAT_FINAL_20261112.json`: `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, zero blockers, and **170 contract-input hashes** including the new compatibility test.
- The previous package 3.61.25 result remains recorded in .audit/V429_CLI_CACHE_FINAL_20261112.json: **1,348 passed, 26 skipped**, RELEASE_HYGIENE=PASS, with 169 contract-input hashes.
- M10, M11, M18, M21 and M25 remain `TESTED`. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.

M21's model manifest no longer sets runtime calibration state. A separately computed `CalibrationReport` is required to lift `UNKNOWN`; its fingerprint and source/sample metadata are bound to the assessment. This protects decision identity but is not a signature over upstream data or producer.

M18 propagates invalidation to a fixed point across graph artifacts, evidence references, gates, candidates and promotions. The recorded revalidation targets are exact for the supplied registries; production-wide registry completeness remains unverified.

M25's V391 application policy now allows exact configured hosts only over HTTPS/WSS on the default TLS port and rejects URL userinfo, malformed ports, invalid zones and non-string endpoints. The application policy is not proof of host/VPC/container enforcement, DNS integrity or actual route separation; M25 remains `TESTED`.

M11's final submit now requires its side-effect journal to use a file-backed SQLite EventStore before a new transport call. The runtime accepts a durable dispatch-attempt ledger; when persistent storage is omitted, it blocks before gateway invocation. This closes the local restart/re-entry path but does not authenticate venue-side idempotency or prove live exactly-once behavior.

M14 now rejects a signed-model object unless it is the exact runtime type returned by the Ed25519-checking loader and carries the loader's verification state. This blocks ordinary constructor, copy and duck-typing bypasses at the live prediction seam. It does not establish a trusted production key source or service deployment; M14 remains `TESTED`.

The source-checkout `scripts/run_offline_acceptance.py` launcher disables bytecode before importing the platform. Its subprocess regression unsets `PYTHONDONTWRITEBYTECODE`, runs an isolated copy of the source tree, verifies the §178 acceptance payload passes, and confirms no cache directories were written. This keeps a normal offline acceptance run from making the next release-hygiene check fail.

Initial V4.29 baseline results:

- V4.29-specific tests: **23/23 PASS**.
- Full repository regression through the mandatory V4.29 runner: **1,180/1,180 PASS**.
- Mandatory runner exit code: `0`.
- `RELEASE_HYGIENE=PASS`.
- Durable preflight: `READY_FOR_MILESTONE`, decision ID `V429-LOCAL-03`, **49 input fingerprints**, no blockers.

## Model-health source binding — M24, package 3.61.17

`HealthAssessment` retains the evidence ID, capture time, TTL, verification flag and assessment time. Authority and capability fingerprints bind this source; commit rejects changed/expired evidence, and durable risk replay recomputes the source fingerprint and rejects mismatches or expired evidence at revalidation. The focused M24/health/durable/release-contract set passed **51 tests** on Windows/Python 3.14.4. The mandatory full runner passed with **1,307 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; `.audit/V429_M24_SOURCE_BINDING_FINAL3_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers and M24 in the impacted set. Inputs are synthetic; `verified=true` is not a signed trust claim. Trusted source identity, independent review and live operational health integration remain open; M24 stays `TESTED`.

## Dynamic drawdown source binding — M23, package 3.61.18

The dynamic drawdown budget now comes from a durable, hash-chained portfolio-equity history. A caller must initialize that history with an explicit opening accounting snapshot, nonempty evidence ID and `verified=True`; later snapshots must be unique and strictly chronological. The assessment records its opening-history evidence ID, current and peak snapshot hashes, validity window, and history fingerprint. Runtime authority binds the current snapshot to accounting truth and rejects unbound scalar inputs. The same assessment fingerprint is retained through execution routing, one-shot capability validation and durable risk decisions; changed or expired sources are rejected at use and restart-safe revalidation. Higher drawdown therefore cannot increase the allowed risk budget.

The focused M23/authority/durable/workflow/release-contract set passed **70 tests** on Windows/Python 3.14.4. The mandatory full V4.29 runner passed with **1,314 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; `.audit/V429_M23_DRAWDOWN_FINAL_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers and M23 in the impacted set.

The `verified` input is only a caller assertion. The local tests use synthetic accounting records and do not establish an independently authenticated opening balance, a trusted history source, live production accounting integration, or independent review. M23 remains `TESTED`, not `VERIFIED`.

## Decision-trace parity integrity — package 3.61.14

Backtest/live trace comparison rejects empty traces, unsupported trace versions, mutable record sequences, invalid or repeated event offsets, non-chronological offsets and content hashes that do not bind the current trace payload. It compares complete per-offset record sequences, so duplicated offsets become mismatches instead of being overwritten by a dictionary. Focused decision, execution-parity, release-integrity and release-hygiene regressions passed **30 tests** on Windows/Python 3.14.7. The production inference adapter and independent M14 review remain unimplemented; this local result does not promote M14 beyond `TESTED` or change production readiness.

The mandatory full V4.29 runner passed with **1,273 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. Durable preflight `.audit/V429_M14_PARITY_PREFLIGHT_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, no blocking reasons, pipeline PASS, and release-hygiene PASS. It retains `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.

## Signed model artifact runtime — package 3.61.15

The local Ed25519-signed JSON model loader validates signature and content hash before parsing a bounded, non-executable model manifest. Schema, version, runtime/dependency/configuration compatibility and prediction constraints are checked; a loaded model used by V3.75 must match the M14 grant's artifact ID and hash. Focused verification passed **76 tests**. The mandatory V4.29 runner passed with **1,291 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; final preflight `.audit/V429_M15_FINAL3_PREFLIGHT_20261111.json` is `READY_FOR_MILESTONE`, `allowed=true`, no blockers, with M14/M15 included. Independent trust-root review and production deployment remain open.

## Persistent credential backend — package 3.61.16

The M9 vault now requires an explicitly persistent backend for production and includes a Windows Credential Manager adapter. The event ledger stores metadata and fingerprints only; active/revoked records replay from the ledger, and resolution verifies the fetched material before returning it. The focused credential/backend, credential-boundary, ledger-concurrency, secret-store policy and release-contract suite passed **62 tests** on Windows/Python 3.14.4. The mandatory runner passed with **1,306 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; final preflight `.audit/V429_M9_M10_CREDENTIAL_FINAL2_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, and no blockers. The Codex sandbox denied a direct native Credential Manager probe with `ERROR_ACCESS_DENIED` before any write, so no real OS credential was written and adapter tests rely on a synthetic API. Dedicated service identity, process isolation and independent deployment attestation remain open.

## Thread-safe durable ledger — M10, package 3.61.16

EventStore now serializes access to each SQLite connection across threads, and iteration holds the lock while streaming rows without copying the full ledger. Credential resolution and revocation serialize through the vault lock; distinct reads at one timestamp receive unique audit IDs. The concurrent append/hash-chain, same-timestamp audit, and resolve/revoke race regressions are included in the 62-test focused suite and the **1,306 passed, 26 skipped** full run above. Independent storage tamper review and operational backup/DR evidence remain open.
- The final archive extraction test and exact inventory/hash comparison are recorded in the external sidecar `V429_ARCHIVE_VERIFICATION.json`.

## Compliance status

The V4.29 matrix contains 42 requirements: TESTED=40, PARTIAL=2. REPO-GOV-01/02 remain PARTIAL pending fresh trusted provider evidence and protected-main validation; no requirement is promoted to VERIFIED from synthetic fixtures or working-branch checks.

## Evidence boundary

Local filesystem tests use temporary directories and synthetic Ed25519 keys. On PR #21, both latest `controlled-milestone-validation` runs on working-branch commit `38613d1b685bf40755a7e41f43a9546973b662ec` succeeded (`43223262302`, `43223245465`). Run `43223262302` reported 1,376 passed, 3 skipped, `RELEASE_HYGIENE=PASS` and uploaded audit artifact ID `13946353746` with digest `sha256:47c8665b9540689e70a295aec2a29eae2b099e83f5c43a8b3a28e4fff8c72b54`. Its separate `REPOSITORY_GOVERNANCE` step reported BLOCKED because the project has no accepted signed provider capture/trust anchor and this PR run is not a protected-main push. Live refs confirm the feature branch at `38613d1b685bf40755a7e41f43a9546973b662ec` and `main` at `85f39b711ea99fb3ad3d9973afb6ba50e5ac27b9`; PR #21 remains open. An authenticated API read confirms strict required checks with administrator enforcement and disabled force-push/deletion; no rulesets are configured, required approvals are zero, code-owner review is disabled and CODEOWNERS maps all paths to @Zenex-cpp. `Zenex-cpp` is the only collaborator; PR #21 has no reviewer or review. These settings are observed but not accepted as independent signed governance evidence. Independent reviewer identity and trust-anchor ceremony remain unverified/not configured.

`external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain unchanged.

## Follow-up verification — 2026-11-11

Package 3.61.11 adds the M25-scoped public historical-data importer and its application-level egress zone. The focused importer, segmentation, workflow-contract, compliance-matrix and release-integrity suite passed **43 tests**. The mandatory Windows/Python 3.14.7 runner passed with **1,255 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; durable preflight returned `READY_FOR_MILESTONE`, `allowed=true`, with M9, M14 and M25 impacted and no blockers.

This patch does not change external evidence or production readiness. M25 remains TESTED pending infrastructure routing proof. No Binance data was downloaded; the public data source is limited by its terms to non-commercial historical research and cannot supply the intended live/commercial strategy. PR #21 hosted CI passed on the working branch; main remains at its older confirmed SHA.

## DATASET-01 audit path — 2026-11-11

Package 3.61.12 adds the local-only user/vendor CSV audit command. No DATASET-01 source file is present in this checkout. Synthetic tests verify contract creation, coverage and hashes, critical/malformed data handling, incomplete temporal coverage, exclusive report creation, repository path refusal, and no-network CLI behavior. This does not count as an audit of a real market dataset or complete source comparison; the source license and definitive-use authority remain unresolved.

Focused CSV/CLI/release-integrity verification passed **15 tests**. The full mandatory Windows/Python 3.14.7 V4.29 runner passed with **1,262 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; durable preflight was `READY_FOR_MILESTONE`, `allowed=true`, with no blockers. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

## DATASET-01 paired-source comparison — 2026-11-11

Package 3.61.13 extends the local CSV audit to compare two bounded local OHLCV CSVs, create separate contracts, normalize timestamp/symbol join keys, report coverage/value differences, and apply explicit bounded numeric tolerances. Automated tests use synthetic files and do not establish source independence, licensing, or the quality of the absent real dataset.

Focused CSV/CLI/release-integrity verification passed **22 tests**. The full mandatory Windows/Python 3.14.7 runner passed with **1,269 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; durable preflight was `READY_FOR_MILESTONE`, `allowed=true`, with no blockers. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

## Hosted branch validation — 2026-11-11

GitHub Actions push run [43042509186](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43042509186) for commit `30ba40ec4ad6f9a76524825f5125c3ca2db86801` completed successfully. Job `controlled-milestone-validation` succeeded. Artifact `V428-validation-audit-43042509186-1` was present (20,205 bytes) with GitHub archive digest `sha256:46558e35e87386132f708063c2e1a460a319c978b33f73c94679d573866a2b2d`. The public artifact metadata was readable, but downloading its contents returned HTTP 401. This run was on the working branch, not protected `main`; REPO-GOV-02 remains `PARTIAL`, and REPO-GOV-01 branch-protection evidence remains `NOT_VERIFIED`.

## M22 source-bound liquidity — package 3.61.19

The focused M22/M23/final-dispatch and matrix/workflow/release-contract verification passed **63 tests**. The mandatory Windows/Python 3.12.14 V4.29 runner passed with **1,322 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, with M22 included and no blockers. Order-book fixtures and market-source records are synthetic. M22 remains `TESTED`; authenticated live feed integration, real-market calibration and independent review remain open. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

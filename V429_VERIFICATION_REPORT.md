# V4.29 Recovery — Verification Report

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

The V4.29 matrix contains 42 requirements: `TESTED=37`, `IMPLEMENTED=2`, `PARTIAL=3`. The governance controls that depend on remote provider evidence remain `PARTIAL` or `TESTED` with explicit unresolved gaps; no requirement has been promoted to `VERIFIED` based only on synthetic fixtures.

## Evidence boundary

All new filesystem tests use local temporary directories and synthetic Ed25519 keys. A live GitHub refresh was attempted but returned no repository data: `gh auth status` reports an invalid token for `Zenex-cpp`, and `git ls-remote` could not resolve `github.com`. No hosted Actions result for this local package revision was observed. Independent reviewer identity and trust-anchor ceremony remain unverified/not configured. This release verifies application behavior; it does not certify production readiness.

`external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain unchanged.

## Follow-up verification — 2026-11-11

Package 3.61.11 adds the M25-scoped public historical-data importer and its application-level egress zone. The focused importer, segmentation, workflow-contract, compliance-matrix and release-integrity suite passed **43 tests**. The mandatory Windows/Python 3.14.7 runner passed with **1,255 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; durable preflight returned `READY_FOR_MILESTONE`, `allowed=true`, with M9, M14 and M25 impacted and no blockers.

This patch does not change external evidence or production readiness. M25 remains `TESTED` pending infrastructure routing proof. No Binance data was downloaded; the public data source is limited by its current terms to non-commercial historical research and cannot supply the intended live/commercial strategy. Hosted GitHub CI and the current remote-main revision still require confirmation.

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

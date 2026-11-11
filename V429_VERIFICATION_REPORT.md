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

## Verification results

- V4.29-specific tests: **23/23 PASS**.
- Full repository regression through the mandatory V4.29 runner: **1,180/1,180 PASS**.
- Mandatory runner exit code: `0`.
- `RELEASE_HYGIENE=PASS`.
- Durable preflight: `READY_FOR_MILESTONE`, decision ID `V429-LOCAL-03`, **49 input fingerprints**, no blockers.
- The final archive extraction test and exact inventory/hash comparison are recorded in the external sidecar `V429_ARCHIVE_VERIFICATION.json`.

## Compliance status

The V4.29 matrix contains 42 requirements: `TESTED=37`, `IMPLEMENTED=2`, `PARTIAL=3`. The governance controls that depend on remote provider evidence remain `PARTIAL` or `TESTED` with explicit unresolved gaps; no requirement has been promoted to `VERIFIED` based only on synthetic fixtures.

## Evidence boundary

All new filesystem tests use local temporary directories and synthetic Ed25519 keys. No live GitHub repository was queried and no hosted GitHub Actions run was observed. Independent reviewer identity and trust-anchor ceremony remain unverified/not configured. This release verifies application behavior; it does not certify production readiness.

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

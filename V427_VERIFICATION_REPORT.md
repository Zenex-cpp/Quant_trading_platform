# V4.27 Recovery Extension — Verification Report

**Disposition:** `READY_FOR_MILESTONE`; `external_evidence=false`; `production_ready=false`.

## Provenance

The source base is the available `trading_platform_v4_25_recovery.tar.gz` with SHA-256 `85d47b572c0a0d6108cb7d32a202fb241a0d91002ecc1356712db02e19ad3515`. The V4.26 recovery archive was not present in this runtime, so this is a V4.27 Recovery Extension from V4.25. Canonical V4.23 continuity and byte-for-byte V4.26 continuity are not established.

## Change summary

- GitHub API content decoding now removes surrounding/line-wrap whitespace only, then uses strict Base64 validation.
- The capture downloader accepts only the two expected preflight audit artifacts and enforces limits of 16 MiB for JSON, 64 MiB for SQLite, and 80 MiB combined.
- The artifact is size-checked before a bounded read; a stat/read size race is rejected.
- The mandatory preflight input fingerprint now includes the new capture-hardening module and its tests.
- Compliance entries `REPO-GOV-CAPTURE-STRICT-01` and `REPO-GOV-CAPTURE-BOUNDS-01` were added as `TESTED`.

## Test results

- Pre-change V4.25 baseline: **1,101/1,101 PASS**.
- Focused V4.27 plus V4.25 capture tests: **25/25 PASS**.
- Full repository regression after changes: **1,113/1,113 PASS**.
- Controlled validation runner (fixed command list): **1,113/1,113 PASS**, exit 0.
- Full regression on the final archive extracted into an independent directory: **1,113/1,113 PASS**, exit 0.
- Release hygiene in the worktree and on the final extracted archive: **PASS**.
- Final manifest: **1,624/1,624 governed files**, zero missing/extra/hash-mismatch files after archive extraction.
- V4.27 compliance preflight: `READY_FOR_MILESTONE`; 4 impacted controls checked; 10 input fingerprints recorded; SQLite event chain verified.
- All tests use offline/synthetic provider fixtures. No remote repository was queried.

## External status

- GitHub remote capture: `NOT_RUN`.
- Hosted GitHub Actions: `NOT_RUN`.
- Actual branch protection/rulesets/CODEOWNERS: `NOT_VERIFIED`.
- Independent reviewer trust anchor: `NOT_CONFIGURED`.
- External evidence: `false`.
- Activation flag: `NOT_SET`.
- Production readiness: `false`.

This release demonstrates strict local parsing and resource-bounded capture behavior only. It does not certify remote repository settings or operational readiness.

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

# V4.28 Recovery Extension — Verification Report

**Disposition:** `READY_FOR_MILESTONE`; `external_evidence=false`; `production_ready=false`.

## Provenance

The available source archive is `trading_platform_v4_27_recovery.tar.gz`, SHA-256 `3e0409eebb3edeebc7a336aa6dc666bef9287cf8abdf45a2ac0f4adff6ca70ac`. The current release is a V4.28 recovery extension from that exact package. Canonical V4.23 and V4.26 byte-for-byte lineage is not established.

## Change summary

- Added V4.28 path policy for governance CLI inputs/outputs: repository-relative inputs, no absolute/traversal/drive/UNC paths, rejection of symlink components, and audit output confinement to `.audit/`.
- Rejected report/event-store collisions and output aliases of protected inputs; included hard-link detection where supported.
- Audit writers use directory file descriptors, `O_NOFOLLOW`, and non-blocking flags where supported; non-regular destinations are rejected.
- GitHub capture validates output paths before authentication/API calls and avoids reserved audit filenames.
- Independent signer output must be external to the checkout and cannot overwrite or alias the private key or unsigned evidence; final symlinks are rejected on write.
- Added V4.28-specific GitHub capture normalizer and repository governance authority. The capture, workflow, and authority agree on `V428_MILESTONE_PREFLIGHT.json`, `V428_MILESTONE_PREFLIGHT.sqlite3`, and `V428-validation-audit-<run_id>-<attempt>`.
- Updated mandatory milestone runner and GitHub workflow to `V4.28-RECOVERY`, baseline `V4.27-RECOVERY`, and `compliance_v428.csv`.

## Test results

- Focused governance/path-policy regression: **87/87 PASS**.
- Full repository regression through the mandatory fixed-command runner: **1,157/1,157 PASS**.
- The first run exposed a release-hygiene failure due to residual `__pycache__` directories. They were removed, and a complete rerun finished with exit code 0 and `RELEASE_HYGIENE=PASS`.
- Durable implementation preflight: `READY_FOR_MILESTONE`, 36 input fingerprints, no blockers, production readiness false.
- Final mandatory preflight/pipeline: `READY_FOR_MILESTONE`, full regression and release hygiene both `PASS`.
- Final archive extraction is independently verified by the external sidecar `V428_ARCHIVE_VERIFICATION.json`.

## Scope limits

All GitHub provider tests use offline/synthetic fixtures. No live repository was queried and no hosted GitHub Actions run was observed. Branch protection, inherited rulesets, effective CODEOWNERS, provider artifact pagination, external reviewer identity, and trust-anchor ceremony remain unverified/not configured. Path-safety tests prove local CLI behavior, not the safety of the host machine or the truth of remote state.

## Safety state

`external_evidence=false`, `activation_flag=NOT_SET`, `production_ready=false`. No trading activation, Testnet mutation, or Production mutation is performed.

# V4.25 Recovery Build — Verification Report

**Date:** 2026-10-12  
**Baseline:** V4.24 Recovery Build archive  
**Disposition:** `READY_FOR_MILESTONE` for local validation; `production_ready = FALSE`.

## Lineage and scope

This is a **Recovery Build**, not a claim of canonical V4.23 source continuity. The actual V4.24 Recovery archive available in this runtime has SHA-256 `5ad06a5cf86efda3d2c9046c9cbea1374967fefb19826148b472acd294dcbfba`. V4.24's own reconstruction note records that the original V4.23 source archive was unavailable. The current work therefore continues the available V4.24 recovery tree and must be replayed onto the original canonical V4.23 tree if that source is restored.

## Local verification results

- Baseline before V4.25 changes: **1,084 tests passed**.
- Targeted governance/capture/signing and V4.25 runner tests: **27/27 passed**.
- Mandatory controlled milestone pipeline: **1,101/1,101 passed**.
- Release hygiene after the test run: **PASS**.
- Mandatory preflight: `READY_FOR_MILESTONE`.
- Compliance Matrix: all impacted governance controls remain explicitly `PARTIAL` or `TESTED`; none is promoted to `VERIFIED` by local fixtures.
- Workflow contract check: `PASS` for the local `.github/workflows/ci.yml` text.

The local pipeline invoked a fixed command list using `shell=False`; it revalidated the matrix, baseline hash and contracted input fingerprints before each step. The machine result is in `V425_LOCAL_VALIDATION_RESULT.json`. The transient event-store files under `.audit/` are working audit records, are excluded from the release package, and are not represented as externally signed evidence.

## Read-only GitHub capture and signing

`src/trading_platform/v425/github_capture.py` and `scripts/capture_github_governance.py` were tested against **synthetic API fixtures only**. The tests cover protected-branch and exact-HEAD scope, rulesets (including inherited sources), required workflow/job, owner/team resolution, CODEOWNERS self-ownership, audit artifact hashing, missing/duplicate files, pagination ambiguity, and scope drift. The separate signer is tested with ephemeral Ed25519 test keys and rejects a private-key path inside the checkout or insecure Unix permissions.

No real target GitHub repository was connected or queried. The diagnostic was run against a placeholder evidence template and returned `BLOCKED`, with `trust_anchor_configured = false` and 31 blocking reasons. This demonstrates fail-closed behavior only; it says nothing about an actual repository's current configuration.

- GitHub-hosted Actions: `NOT_RUN`.
- Remote branch protection/rulesets/CODEOWNERS: `NOT_VERIFIED`.
- Independent signer identity and public-key trust ceremony: `NOT_CONFIGURED`.
- External evidence: `false`.
- `production_ready`: `false`.
- `activation_flag`: `NOT_SET`.

## Package verification

The release manifest and archive hashes are published separately. The final archive is extracted into a fresh directory; the complete regression and release-hygiene check are repeated there; then the file inventory and SHA-256 values are compared against the manifest. Results are recorded in `V425_ARCHIVE_VERIFICATION.json` outside the archive to avoid self-referential hashes.

## Conclusion

V4.25 provides a testable, read-only path for capturing GitHub governance evidence and signing it on a separate reviewer system. It does **not** state that remote controls are currently configured, that GitHub Actions has run, or that the platform is production-ready. Canonical lineage, remote settings, independent trust anchor, hosted CI and all operational production blockers remain open.

# V3.64 Release Notes

## Scope
Master Prompt §176 evidence integrity: explicit external-provenance boundary for production-readiness evidence.

## Problem addressed
V3.60/V3.61 documented that production-readiness evidence must be externally sourced, but the machine contract only rejected `demo:` / `synthetic:` references. An internally generated package could therefore reach the verification API if it used a non-synthetic-looking reference.

## Implementation
- Added `EvidenceSourceKind` with `EXTERNAL`, `INTERNAL`, `SYNTHETIC`, and `UNKNOWN`.
- Persisted `source_kind` in the durable readiness-evidence record and fingerprint.
- `ReadinessEvidenceLedger.verify()` now fails closed unless `source_kind == EXTERNAL`.
- Legacy V3.61 imports without explicit provenance are preserved as `UNKNOWN` and therefore cannot be verified.
- Added `ExternalEvidencePackageImporter`, which requires explicit `EXTERNAL` provenance before package import into the production-readiness path.
- Fixed the evidence-package template so the SHA-256 field is an explicit 64-hex placeholder instead of an empty string.
- Added regression coverage for internal, legacy/unknown, synthetic, and valid external evidence paths.

## Verification
- Full suite: **653 passed**.
- External evidence boundary tests: PASS.
- Legacy package without provenance cannot become VERIFIED: PASS.
- Restart/replay persistence of provenance: PASS.

## Production readiness
`production_ready = FALSE`.

This release is a governance/evidence-integrity hardening only. It does not create venue evidence, independent human approval, infrastructure/network evidence, production credentials, or live authorization.

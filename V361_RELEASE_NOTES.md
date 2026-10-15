# V3.61 Release Notes

## Scope
External readiness evidence submission boundary.

## Implementation
- Added `EvidencePackageImporter` and durable `READINESS_EVIDENCE_PACKAGE_IMPORTED` audit.
- Package import is atomic across package metadata and submitted evidence artifacts.
- Import only creates `SUBMITTED` evidence; it never creates `VERIFIED` evidence and never grants production approval.
- External source references are required; synthetic/demo sources are rejected.
- Sensitive credential-like fields are rejected from evidence packages.
- Package hash and per-evidence content hash are required.
- The imported package is restart-safe and replay-auditable.

## Operational rule
Real external evidence must be supplied from the appropriate production/infrastructure systems and independently reviewed. Automated tests do not create those evidences.

# V3.67 Backup / Restore Drill Contract

## Scope
V3.67 adds a local, deterministic backup/restore drill for governed test artifacts.
It is **INTERNAL_TEST_EVIDENCE** and does not satisfy the production infrastructure evidence required by the V3.59 Open Gaps Register.

## Contract
- Source paths are explicitly allowlisted.
- Secret-like paths are rejected.
- Backup captures a canonical manifest with SHA-256 hashes.
- Restore requires an empty destination.
- Archive members are checked for path traversal, symlinks and undeclared files.
- Restored files are hash-verified against the manifest.
- RPO and RTO targets fail closed when exceeded.

## Evidence boundary
This drill proves the application-level backup artifact format and restore procedure only. It does not prove production database durability, object-store durability, off-site retention, infrastructure RPO/RTO, or disaster recovery readiness.

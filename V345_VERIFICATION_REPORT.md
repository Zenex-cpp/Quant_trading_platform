# V3.45 Verification Report

Requirement: M18 — No promotion without Evidence Snapshot.

Status: TESTED
production_ready: FALSE

## Evidence
- `EvidenceSnapshotAuthorityLedger` persists `EVIDENCE_SNAPSHOT_AUTHORIZED` in the append-only EventStore.
- The persisted snapshot contains immutable evidence IDs, metrics, gates, dependencies, versions, artifact hashes, methodology, approvals, scope and the exact content hash.
- The content hash and metrics hash are recomputed before reuse.
- The snapshot is bound to the exact promotion ID, Promotion Bundle ID and model version.
- Promotion rechecks gate IDs, artifact hashes, versions, approval and requested scope against the immutable snapshot.
- Dependency checkpoint reuse is fail-closed: any later invalidation touching the snapshot dependency set makes the snapshot stale, even after revalidation.
- Champion/Challenger promotion requires both the durable Champion Gate Authority and durable Evidence Snapshot Authority.
- The legacy promotion checker also requires a durable Evidence Snapshot Authority, preventing a secondary promotion surface from bypassing M18.
- Restart persistence is covered through a reopened SQLite EventStore.
- Event-store tampering fails closed through the existing hash-chain verification.

## Tests
- Full suite: 524 passed.
- Focused M18 suite: 8 passed.
- `compileall`: PASS.

Independent review of the evidence snapshot store/content binding and complete cross-system evidence graph invalidation remains outstanding; therefore M18 is TESTED, not VERIFIED.

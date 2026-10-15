# V3.96 Release Notes

V3.96 adds an external operational backup/disaster-recovery attestation intake boundary above the existing application-level DR exercise.

## Scope

The authority accepts external DR evidence only when:

- the exact runtime DR policy snapshot is bound by version/hash;
- observed RPO and RTO satisfy hard limits;
- backup artifact and restore evidence are bound by hashes;
- failover, failback and recovery-proof references are external and non-synthetic;
- recovery reconciliation, invariants and guards all pass;
- operator, custodian and reviewer identities are separated;
- a separately trusted Ed25519 reviewer key is active, scoped and unexpired;
- the canonical attestation signature verifies;
- the acceptance event is durably recorded and idempotent.

## Safety boundary

V3.96 does not manufacture backup, restore, failover or infrastructure proof. Internal application-level drills remain internal evidence. External evidence must be produced by the operational environment and independently reviewed.

## Readiness

The V3.96 implementation is TESTED. External backup/restore execution, cross-region durability, actual failover/failback, independent reviewer operation and production monitoring remain external evidence requirements and are NOT_VERIFIED by this release.

# V3.37 — M10 immutable record version/audit enforcement

M10 is implemented as a machine-checkable immutable-record boundary.

- EventStore records are database-level append-only: UPDATE/DELETE are rejected.
- Durable checkpoints are append-only and reject UPDATE/DELETE.
- Durable evidence artifacts are append-only and reject UPDATE/DELETE.
- `ImmutableRecordAuthority` represents a change as a new version plus an immutable audit event; in-place mutation is rejected.
- Version and audit are written atomically in one EventStore transaction.
- The version/supersession chain is validated against the EventStore hash chain.
- Existing mutable operational state is not reclassified as immutable by this release.

Verification snapshot: 476/476 full-suite tests passed; 6/6 dedicated M10 tests passed; compileall passed. No live/testnet network request or real credential was used.

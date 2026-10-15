# V3.29 Release Notes

V3.29 introduces a durable dependency invalidation authority for the Evidence/Promotion chain.

Changes:
- new `trading_platform.v329.dependency_authority` module;
- append-only `EVIDENCE_DEPENDENCY_INVALIDATED` events with graph-version and blast-radius binding;
- append-only `EVIDENCE_DEPENDENCY_REVALIDATED` events;
- idempotent invalidation and revalidation identities;
- restart-safe active/closed invalidation state reconstructed from EventStore;
- fail-closed behavior on corrupted EventStore chains;
- explicit guards for evidence, gate and promotion reuse;
- final V3.25 deployment activation now checks the durable invalidation ledger before accepting promotion authority;
- unresolved invalidation blocks deployment even when existing approval and promotion inputs otherwise pass.

Limits:
- legacy evidence producers are not yet universally wired to emit invalidation events;
- legacy direct gate-reuse callers are not yet universally forced through the authority.

Verification: **422/422 tests passed**.
No live/Testnet exchange request or real credential was used.
`production_ready = FALSE`.

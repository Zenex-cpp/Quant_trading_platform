# V3.72 Change Impact

## Changed component
`src/trading_platform/v372/dr_exercise.py`

## Dependencies
- `trading_platform.ops.backup_restore`
- `trading_platform.v21.event_store.EventStore`
- `trading_platform.v21.ledger.EventSourcedLedger`
- `trading_platform.v23.recovery.GapRecoveryCoordinator`
- `trading_platform.v23.recovery.RestSnapshot`

## Safety impact
The exercise is fail-closed. A missing/invalid chain, invalid snapshot, replay mismatch, invariant failure, unresolved critical issue, or RTO breach prevents `trading_allowed`.

## Evidence boundary
The evidence is `INTERNAL_TEST_EVIDENCE`. It is not sufficient for production DR readiness.

## Revalidation triggers
- changes to backup/restore contract;
- event-store format changes;
- recovery coordinator changes;
- snapshot schema changes;
- recovery invariants changes.

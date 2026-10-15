# V3.13 Release Notes

V3.13 makes execution correlation restart-safe.

## Contract

`intent_id ↔ order_request_id ↔ clientOrderId ↔ exchangeOrderId`

is now durably persisted in SQLite with uniqueness constraints in both directions. The same database also journals user/exchange evidence events with idempotent `event_id` insertion.

A process restart can reconstruct the correlation without trusting in-memory state. Conflicts are fail-closed; exchange IDs cannot be silently rebound to another intent.

Credentials, socket handles and transport state are not persisted.

## Safety

A journaled event without a known correlation does not create an intent and does not create a fill. Unknown execution evidence remains available for reconciliation.

## Verification

The release is required to pass the complete regression suite and a second run from the extracted tarball. No live/Testnet exchange calls are part of verification.

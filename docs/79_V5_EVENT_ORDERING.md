# V5 Event Ordering Contract

This contract implements prompt §28 for events that use the canonical `EventEnvelope`.

## Deterministic batch/replay order

`order_events` validates each envelope and orders by:

1. `event_time`, normalized to UTC;
2. exact `source` identifier;
3. source-local `sequence_number` when present, with sequenced records before records missing a sequence at the same time and source;
4. `receive_time`, normalized to UTC;
5. `event_id`.

Sequence values are compared only within the same source. Lexicographic source ordering resolves equal-time multi-source replay deterministically; it does not assert that one venue event caused or happened before another. If sorted event time conflicts with increasing source sequence, replay fails closed instead of choosing one clock as authoritative.

## Live stream handling

`EventStreamOrderGuard` maintains an in-memory cursor per source and enforces the same equal-time tie key as batch ordering. It rejects event-time regression, non-increasing source sequence, same-time tie-key regression, and duplicate event IDs. Where sequence values are absent, receive time and event ID provide the tie-break. The caller must replay or rebuild the affected source before resuming. Sequence gaps cannot be detected while the source omits sequence numbers.

The guard is process-local. It does not persist cursors, deduplicate across restarts, validate event payload schemas, or guarantee exactly-once delivery. Production callers must bind the cursor to durable source state and apply the §29 idempotency contract separately.

## Machine-readable policy

`schemas/v5_event_ordering_policy.csv` records the ordering key, source-local sequence rule, missing-sequence behavior, late-event response, multi-source tie-break, and recovery action.

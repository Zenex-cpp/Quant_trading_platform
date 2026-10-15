# V4.4 Change Impact

The change is isolated to a new V4.4 authority and tests. No order-dispatch, accounting, market-data or exchange adapter path is modified.

The new authority is intentionally a governance boundary: it consumes durable EventStore state and signed reviewer input, writes only an append-only revocation record, and does not perform network or process egress.

The control is compatible with the fail-closed requirement: once a revalidation witness is revoked, downstream consumers must reject it regardless of remaining TTL.

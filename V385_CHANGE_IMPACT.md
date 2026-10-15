# V3.85 Change Impact

Changed component:
- controlled Testnet mutation boundary (`v385`)

Affected components:
- V384 activation authority
- V380 order adapter
- V321 durable dispatch attempt ledger
- EventStore audit chain
- Testnet execution evidence

New invariants:
- No external submit without a valid pre-trade snapshot.
- No external submit without a durable dispatch-attempt claim.
- A pending/unknown dispatch attempt cannot be retried blindly.
- Snapshot intent/request binding mismatch blocks submission.
- Unknown position, unreconciled accounting, non-green reconciliation or stale market data block new risk.

Historical versions:
- V3.84 and earlier are not modified.

Open downstream validation:
- real authenticated Testnet submit;
- private user-data event receipt;
- REST/WebSocket reconciliation after mutation;
- end-to-end accounting on exchange-observed fills.

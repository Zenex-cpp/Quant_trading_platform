# V1.7 — End-to-End Testnet Workflow

V1.7 adds an operational workflow layer on top of the prior Testnet verification components. It is deliberately fail-closed.

## Invariants

- Environment is TESTNET only.
- Network policy rejects known production hosts.
- Default execution is plan/read-only; mutations are never enabled by default.
- Mutation requires explicit operator approval, an approval TTL, a hard notional cap, green reconciliation, fresh decision state and an inactive kill switch.
- Evidence is persisted in SQLite and sealed with SHA-256. Reusing an evidence ID with a different payload is rejected.
- Offline evidence never becomes live evidence.

## Operational sequence

TN-01 connectivity → TN-02 exchange rules → TN-03 authenticated account → TN-04 order-test contract → TN-05 controlled order → TN-06 cancellation → TN-07 unknown-order reconciliation → TN-08 account/position reconciliation → TN-09 restart/recovery → TN-10 failure injection.

The current CLI executes the first two scenarios only when `--network-read-only` is explicitly supplied. Mutating stages remain a gated integration contract and are not executed automatically.

## Binance references

The current Binance developer documentation remains the authoritative external reference for USDⓈ-M REST and WebSocket APIs. Endpoint details are versioned in the evidence references and must be revalidated when Binance changes the API surface.

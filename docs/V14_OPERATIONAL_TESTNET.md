# V1.4 — Operational Testnet Evidence

## Scope
V1.4 introduces the operational testnet session coordinator and durable evidence capture.

The default executable plan is read-only (`TN-01`, `TN-02`). Trade-mutating scenarios remain separately guarded and are not enabled by the default runner.

## Safety boundary
- environment must be `TESTNET`;
- TLS required;
- Binance mainnet hosts rejected;
- credentials supplied only at runtime;
- secret values are excluded from evidence metadata and serialized artifacts;
- network execution requires an explicit `allow_network=True` call;
- no production endpoint or production credential is accepted by design.

## Live verification status
The presence of the runner does not constitute evidence that an exchange session succeeded. A scenario becomes `PASSED` only after an actual network response satisfies its scenario probe and its evidence artifact is persisted and hashed.

## Required operational sequence
TN-01 connectivity → TN-02 exchange rules → TN-03 order acknowledgement → TN-04 cancellation → TN-05 partial fill → TN-06 full fill → TN-07 unknown-order reconciliation → TN-08 restart/reconnect → TN-09 account/position reconciliation → TN-10 fee/funding reconciliation → TN-11 failure-injection recovery.

TN-03…TN-10 require a dedicated, explicitly approved mutation plan and real Testnet account. They are not silently promoted by read-only probes.

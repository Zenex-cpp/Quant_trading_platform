# V3.12 Release Notes

V3.12 closes the execution-runtime integration gap between the authoritative runtime permission, the committed `ExecutionBridge` request, and the Binance USDⓈ-M Testnet gateway.

## Scope

`V3.10 runtime authority -> V3.11 dispatch guard -> V3.34 ExecutionBridge -> V3.35 Binance Testnet gateway`

The new `ExecutionRuntimeIntegration` is deliberately narrow:

- it never rebuilds an order;
- it dispatches only the already committed `OrderRequest`;
- it performs a final `trading_allowed` check immediately before network dispatch;
- transport uncertainty is converted to local `UNKNOWN` and reconciliation-required state;
- a permission loss detected after the network boundary is not represented as a clean successful cycle; the exchange observation is retained and recovery is required;
- no network call is made when runtime permission is absent.

## Failure-injection contract

The test suite covers:

1. clean runtime-authorized dispatch;
2. transport uncertainty after submit boundary;
3. permission loss during/after the dispatch cycle;
4. blocked runtime with zero gateway calls.

## Safety status

No real credentials were used. No Binance/Testnet calls were made. The package remains a controlled/Testnet implementation and is not production-ready.


Current lineage checkpoint: V3.36 Research credential boundary (M9).

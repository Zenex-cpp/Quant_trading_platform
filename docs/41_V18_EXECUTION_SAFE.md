# V1.8 — Execution-safe Testnet contract

V1.8 extends V1.7 without changing the production-safety posture. It adds a deterministic `OrderIntent`, an execution adapter, the Binance USDⓈ-M Test Order contract, and explicitly gated place/query/cancel paths.

Hard rules:

- Environment remains TESTNET-only.
- Default mode is `TEST_ONLY`.
- Order notional is capped by the workflow hard cap.
- Market orders require an explicit reference price for deterministic risk bounding.
- Live order placement and cancellation require an unexpired `MutationApproval`, green reconciliation, fresh decision state, successful preflight, and no kill switch.
- Order identifiers are required for query/cancel; blind retry is not provided.
- Every externally visible execution step produces durable hashed evidence.

The verified Binance documentation currently identifies `POST /fapi/v1/order/test` as the USDⓈ-M Test Order endpoint and `POST /fapi/v1/order` as New Order. The adapter keeps endpoint strings local to the Testnet execution boundary rather than scattering them across research code.

No live mutation was executed during V1.8 build verification.

# V1.8 Release Notes

Implemented:

- deterministic `OrderIntent` and bounded notional validation;
- `TEST_ONLY` order path using `/fapi/v1/order/test`;
- explicit-gate live Testnet place/cancel/query adapter;
- durable evidence for test-order and controlled-order acknowledgement;
- deterministic client order IDs;
- regression tests for caps, gating, deterministic IDs, test order, place/cancel.

Verification target: all historical V0.1–V1.7 tests plus V1.8 tests must pass.

Production status: NOT READY. V1.8 adds execution contracts and gates; it does not authorize Mainnet or remove human approval requirements.

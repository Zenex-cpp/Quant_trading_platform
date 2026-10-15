# V3.19 — Durable OrderIntent Authority

V3.19 makes `OrderIntent` an explicit durable authority artifact at the final dispatch boundary.

The ledger is append-only, hash-chained and idempotent through the existing event store. An `intent_id` may not be reused with different payload. The complete intent identity is fingerprinted, including causal identifiers, strategy/model/execution versions, symbol/side/action/quantity/order type, validity window, limit price, time-in-force and reservation binding.

The V3.18 final dispatcher accepts an optional `DurableOrderIntentLedger`. When configured, the dispatcher requires the submitted intent to exist in the durable ledger and to match its persisted fingerprint before any risk gate or external transport can proceed.

A missing, corrupted or mismatching durable intent is fail-closed. The ledger contains no credentials or transport state.

This is an authority/evidence layer; recording an intent does not itself authorize trading. Existing accounting, reservation, risk-decision, runtime-permission and exchange-boundary gates remain mandatory.

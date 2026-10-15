# V3.18 Release Notes

V3.18 closes the durable RiskDecision and final freshness gap at the external dispatch boundary.

Added:
- durable, hash-chained `RiskDecisionRecord` ledger;
- explicit risk actions and risk-system states;
- requested/allowed exposure, limits and multiplier traceability;
- reservation/intent binding;
- valid-from / expiry TTL;
- configuration, risk-state, portfolio and position version fields;
- provenance, truth hash and input fingerprint;
- restart/replay recovery and immutable decision-id idempotency;
- fail-closed final validation for expired/future/non-ALLOW/frozen/emergency/recovery decisions;
- committed `OrderIntent` identity verification before transport;
- one captured clock sample shared by OrderIntent, OrderRequest, RiskDecision and RiskReservation freshness checks.

Safety posture:
- no credentials persisted;
- no autonomous network I/O added;
- no Binance live/Testnet request executed by the verification suite;
- `production_ready = FALSE` remains unchanged.

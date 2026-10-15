# Compliance Report — V0.2

Automated contract tests: 16 passed.

Status policy:
- IMPLEMENTED = code + automated test.
- TESTED = automated test evidence is available.
- VERIFIED = implementation + tests + evidence + review.
- PRODUCTION_READY = VERIFIED + operational readiness + security + recovery + approval.

No V0.2 item is claimed VERIFIED without the evidence/review layer.

## V0.6
Portfolio allocation, capacity, turnover and risk-budget integration implemented/tested. Advanced allocation methods remain registered but deferred.

## V3.17
V3.17 closes the durable risk-reservation boundary. The final dispatch gate can require a durable reservation bound to intent, risk decision and accounting projection hash, with fail-closed handling for missing, stale, expired or consumed reservations. See `V317_VERIFICATION_REPORT.md` and `compliance_v317.csv`.


## V3.21 Delta

V3.21 adds durable pre-transport dispatch-attempt authority. The final dispatch path records a `PENDING` attempt before external I/O, binds it to the exact V3.19 `OrderIntent` and V3.20 `OrderRequest` fingerprints, records the resulting execution state, and blocks reuse of the same `OrderRequest` after `PENDING`, `UNKNOWN`, or resolution. This closes the process-crash window in which an exchange side effect could otherwise be retried without a durable marker.

Verification: 357 tests passed; Python compile check passed; no live/Testnet exchange request or real credentials used; `production_ready = FALSE`.


## V3.22
Durable dispatch reconciliation and recovery gate integration: VERIFIED.

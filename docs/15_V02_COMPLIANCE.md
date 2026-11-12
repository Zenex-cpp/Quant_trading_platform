# V0.2 Compliance Position

`IMPLEMENTED` means the contract exists in code and is covered by an automated test in this repository. It does not mean `VERIFIED` or `PRODUCTION_READY`.

V0.2 closes these concrete gaps:
- transition idempotency primitive;
- risk budget reservation primitive;
- hard risk ceiling helper;
- configuration precedence and conflict detection;
- order construction guards;
- fill duplicate protection;
- position projection;
- reconciliation/recovery proof predicate;
- statistical assumption applicability;
- event schema registration;
- evidence snapshot structure.

Dependency invalidation now closes transitively across artifact nodes, evidence source/dependency references, gates, candidates and promotions in the registries supplied to each invalidation. Remaining blockers include production-wide registry completeness, signed evidence and independent review, venue reconciliation, final holdout operational proof, failure injection and production review.

# V3.97 Release Notes — Security + Monitoring Readiness

V3.97 adds a machine-checkable admission authority for the two operational-readiness evidence families that remained outside the application contract:

- independent external security assessment;
- external production monitoring / alerting evidence.

Hard controls include exact policy/release binding, zero unresolved CRITICAL findings and policy-bounded HIGH findings, complete critical-signal coverage, alert delivery latency, on-call response, trusted Ed25519 reviewers, reviewer/source independence, TTL, non-synthetic evidence references, sensitive-material rejection, and durable idempotent acceptance.

Verification:
- focused tests: 15/15 PASS
- full regression: 939/939 PASS

External security assessment and production monitoring operation remain NOT_VERIFIED.
`production_ready = FALSE`.

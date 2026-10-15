# V3.93 Release Notes

V3.93 adds the machine-checkable external-evidence independent-review authority for
Master Prompt §113–§176 and closes the application-level admission gap between an
`EXTERNAL` evidence package and a production-critical independent review.

Implemented:
- durable accepted-review record in the append-only EventStore;
- exact package/evidence subject coverage;
- reviewer independence from evidence producers, owners and approvers;
- review validity window and bounded TTL;
- external source provenance and synthetic/demo-source rejection;
- explicit signature reference, signature hash and externally-verified signature state;
- deterministic review hash and fingerprint;
- idempotent review admission and hash-chain verification;
- secret-free review payload contract.

Non-goals:
- no claim of real PKI/HSM signature verification;
- no external reviewer access;
- no change to live/Testnet execution authority;
- no production readiness override.

External review and infrastructure evidence remain required and `production_ready`
remains `FALSE` until independently supplied and reviewed evidence exists.

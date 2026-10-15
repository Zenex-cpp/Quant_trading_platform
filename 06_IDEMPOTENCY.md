# 06 — Idempotency Contract

Every side-effecting operation carries an idempotency key.

Required domains:
ingestion, event processing, order submission, cancel, replace, reconciliation, deployment, recovery, state transition.

Duplicate handling contract:
1. locate prior operation by idempotency key;
2. verify same operation payload/hash;
3. return prior result without repeating side effect;
4. if key collision with different payload → CRITICAL integrity error.

# 06 — Idempotency Contract

## Durable event store key binding

`EventStore.append` returns the prior event only when a retry with the same `event_id` produces the same canonical event hash across timestamp, type, aggregate, and payload. Reusing an ID with changed content raises `EVENT_APPEND_CONFLICT`; it does not report a duplicate or alter the chain. Exact repeated payloads with different mapping insertion order remain equivalent after canonicalization.

## Transition engine enforcement

The in-memory TransitionEngine binds each committed idempotency key to the complete TransitionSpec and result. An identical retry returns the committed result without rerunning its guard or adding another audit event. Reusing the key with a different source, target, action, transition ID, audit event type, or guard is rejected with IDEMPOTENCY_KEY_CONFLICT.

Every side-effecting operation carries an idempotency key.

Required domains:
ingestion, event processing, order submission, cancel, replace, reconciliation, deployment, recovery, state transition.

Duplicate handling contract:
1. locate prior operation by idempotency key;
2. verify same operation payload/hash;
3. return prior result without repeating side effect;
4. if key collision with different payload → CRITICAL integrity error.

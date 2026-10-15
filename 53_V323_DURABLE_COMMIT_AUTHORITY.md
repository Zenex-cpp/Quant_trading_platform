# V3.23 — Durable Commit Authority

V3.22 closed unresolved dispatch attempts, but `CommitCoordinator` still kept its commit/idempotency state only in memory. V3.23 adds a durable commit claim so an exact `OrderIntent` cannot create a second committed `OrderRequest` after restart.

## Contract

`validate capability -> construct exact request -> durable commit claim -> consume capability -> local submitted state`

The durable claim contains the exact commit fingerprint, intent fingerprint, capability identity/expiry, authority decision and complete normalized OrderRequest. It contains no credentials, sockets, raw transport objects or exchange response bodies.

## Safety invariants

- A durable commit claim is written before capability consumption.
- A second process seeing the same exact Intent returns the original committed request and does not consume a new capability.
- Reusing the same `intent_id` with a different commit fingerprint fails closed.
- A corrupt EventStore chain prevents durable reuse.
- Concurrent insert races cannot grant a second commit.
- If memory claims a commit while the durable record is absent, the configured durable coordinator fails closed rather than silently recreating the commit.
- Existing V3.18 risk, V3.19 intent, V3.20 request, V3.21 attempt and V3.22 reconciliation gates remain downstream requirements.

## Restart semantics

A crash after the durable claim but before capability consumption is treated as a duplicate on restart. This is intentional: no external transport occurs at the commit point, and the durable claim prevents recreation of the same economic action.

## Scope

The ledger is an execution-authority primitive. It does not authorize trading by itself and it does not bypass Operational Truth, risk, accounting, permission, dispatch-attempt or exchange reconciliation gates.

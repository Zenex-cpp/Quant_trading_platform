# V3.20 — Durable OrderRequest Authority

V3.19 made `OrderIntent` durable. V3.20 extends the same authority chain to the committed `AuthorizedOrderRequest`, which is the exact request that can cross into external execution transport.

The durable record contains the complete `AuthorityDecision` plus the complete `OrderRequest`, together with the fingerprint of the originating `OrderIntent`. It is append-only and hash-chained through the existing `EventStore`.

The V3.4 bridge can optionally record every committed request. The V3.11 final dispatcher can optionally require the durable request and reject missing, corrupted, mismatching, or stale intent-fingerprint bindings before subsequent risk gates or transport.

Recording remains evidence/authority state only. It does not by itself authorize trading, persist credentials, or perform exchange I/O. Existing accounting, reservation, risk-decision, runtime-permission, intent, lifecycle, and exchange-boundary gates remain mandatory.

Safety outcome:
- unknown or missing durable request => no dispatch;
- request payload substitution => no dispatch;
- intent-fingerprint substitution => no dispatch;
- corrupted event chain => fail closed;
- credentials and transport objects are not persisted.

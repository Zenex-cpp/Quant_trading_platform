# V5.0 Causal Artifact Chain

The canonical chain required by MASTER PROMPT §§21–22 is recorded in
`schemas/v5_causal_artifact_chain.csv`:

`Prediction → Signal → Opportunity → Portfolio Decision → Risk Decision →
Order Intent → Order Request → Exchange Order → Fill → Position → Portfolio →
Accounting → P&L`.

Every node requires identity, version, timestamp, TTL, explicit dependency IDs,
state, provenance, and a fingerprint. The machine-readable validator recursively
checks every referenced ancestor for registered type, required fields, valid
state, timestamp order, and an active TTL window; a downstream expiry cannot
outlive any direct upstream expiry. The durable V3.333 ledger enforces the
runtime TTL/state chain through `Order Intent`; later execution and accounting
authorities enforce their own durable identities and reconciliation checks. A
downstream artifact cannot authorize itself when an upstream record is missing,
invalid, expired, or changed.

This closes the canonical artifact gap while retaining the explicit operational
boundary: venue truth, production identity, and cross-service store wiring still
need external evidence.

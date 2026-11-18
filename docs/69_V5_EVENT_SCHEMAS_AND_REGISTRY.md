# V5 Event Envelope, Payload Schemas, and Registry

This artifact implements the §26 envelope fields and a schema registry for the typed event streams that already expose stable event dataclasses.

## Canonical artifacts

- `schemas/v5_event_envelope.v1.schema.json` defines the shared envelope shape.
- `schemas/v5_event_schema_registry.csv` records 27 versioned registrations across 26 event types: 19 typed V2.7 governance/deployment/provenance events, four production credential-vault events, three V3.15 durable-accounting events, and a v0.9 registration schema retained for legacy ledger replay.
- `schemas/v5_event_payload_schemas/` contains versioned payload contracts for those streams and credential lifecycle events.
- `src/trading_platform/events/registry.py` loads the registry, enforces unique `(event_type, version)` and `schema_id` keys, confines schema references to the local schema directory, validates envelope chronology, and validates event payloads against JSON Schema. Payload validation can also be called directly for durable events whose store does not carry the canonical envelope.
- `ProductionCredentialVault` requires an injected registry in production. It validates credential register, revoke, resolve, and denied-resolution payloads before append, and validates those records again while restoring the ledger. The legacy registration schema accepts pre-authorization records that have no `actor_role`; new records use v1.
- `DurableAccountingLedger` requires a complete injected registry when backed by persistent storage. It validates fill, funding, and cash-adjustment payloads before append and again during reconstruction after event-chain verification. In-memory ledgers may omit the registry for isolated compatibility tests.
- The realtime `MarketEvent` uses the canonical `EventEnvelope` implementation.
- `docs/79_V5_EVENT_ORDERING.md` and `schemas/v5_event_ordering_policy.csv` define deterministic §28 batch/replay ordering and fail-closed live handling for late or out-of-order records.

`compatibility_mode` is recorded as `NONE`: the prompt requires the field but does not define a compatibility policy. The registry does not infer a compatibility guarantee. Event type names are domain-qualified because identical labels such as `ROLLBACK` occur in more than one stream.

## Verified boundary and remaining gap

The 19 typed V2.7–V2.9 event values are checked against their dataclass fields. Four credential-vault and three durable-accounting event types have strict payload schemas and write/replay validation at their production boundaries. The §28 ordering helper is separately tested, but it does not validate payload schemas or persist stream cursors.

This is not yet a platform-wide catalog. The V2.1 generic `EventStore` and many later durable authority ledgers still accept event types and payloads without the registry. The generic store also does not persist the canonical envelope or schema version; the credential vault selects v0.9 only for a legacy registration payload that lacks `actor_role`. The accounting ledger currently selects v1.0 in code because its generic store records no schema version. Remaining producers, consumers, schemas, migrations, and envelope wiring still need inventory and enforcement. FD-10 and FD-11 therefore remain `PARTIAL`.

The runtime schema validator uses the `jsonschema` dependency declared by the package. Registered references may not traverse outside the local schema root or load remote `$ref` documents.

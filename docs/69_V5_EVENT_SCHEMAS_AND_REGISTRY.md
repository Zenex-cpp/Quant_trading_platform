# V5 Event Envelope, Payload Schemas, and Registry

This artifact implements the §26 envelope fields and a schema registry for the typed event streams that already expose stable event dataclasses.

## Canonical artifacts

- `schemas/v5_event_envelope.v1.schema.json` defines the shared envelope shape.
- `schemas/v5_event_schema_registry.csv` records all 19 registered event types from the V2.7 governance, V2.8 deployment, and V2.9 provenance streams.
- `schemas/v5_event_payload_schemas/` contains the versioned payload contracts for those three streams.
- `src/trading_platform/events/registry.py` loads the registry, enforces unique `(event_type, version)` and `schema_id` keys, confines schema references to the local schema directory, validates envelope chronology, and validates event payloads against JSON Schema.
- The realtime `MarketEvent` uses the canonical `EventEnvelope` implementation.

`compatibility_mode` is recorded as `NONE`: the prompt requires the field but does not define a compatibility policy. The registry does not infer a compatibility guarantee. Event type names are domain-qualified because identical labels such as `ROLLBACK` occur in more than one stream.

## Verified boundary and remaining gap

The registry is complete for the 19 event values in the three typed enums and is checked against their actual dataclass fields. It is not yet a platform-wide event catalog: the V2.1 generic `EventStore` and many later durable authority ledgers accept their own event types and payloads without using this registry. Those producers, consumers, versions, migration references, and payload schemas still need to be inventoried and wired to validation. FD-10 and FD-11 therefore remain `PARTIAL`.

The runtime schema validator uses the `jsonschema` dependency declared by the package. Registered references may not traverse outside the local schema root or load remote `$ref` documents.

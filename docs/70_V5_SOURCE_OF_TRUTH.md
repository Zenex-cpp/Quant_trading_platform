# V5.0 §179 Source-of-Truth Matrix

This matrix names the authoritative record for each project and trading domain, the identity/version binding used to compare records, and the required response to disagreement. Its machine-readable register is `schemas/v5_source_of_truth_matrix.csv`; `tests/test_v5_source_of_truth_matrix.py` checks the domain inventory and repository references.

## Authority rules

1. Authority is domain-scoped. Configuration precedence applies only to configuration values; it does not decide between market-data revisions, exchange observations, or accounting records.
2. Compare records only when their scope, identity, version, timestamp, and content hash are compatible. Derived records retain references to their inputs and must not silently replace them.
3. When a required authoritative record is missing, stale, conflicting, or unverifiable, preserve `UNKNOWN`/blocked status and stop any dependent risk-increasing action, promotion, or deployment. Reconcile against the domain's authority and record a new version; never resolve a disagreement by picking whichever value is newest or most convenient.
4. A local ledger is authoritative only for the records it durably stores and validates. A default in-memory store, report, cache, working tree, or generated audit file is not proof of durable operational state.
5. `EXTERNAL_REQUIRED`, `PARTIAL`, and `DURABLE_IF_CONFIGURED` rows identify explicit limits. This matrix does not assert that an external source is connected, independently authenticated, protected, licensed, or production-ready.

## Matrix scope

The matrix covers the 25 cross-domain records currently present or required by the repository and prompt: specification, source tree and package release; configuration; raw and normalized data; feature/prediction and model artifacts; event, research, evidence, gate, champion, promotion and deployment records; order, fill, position, accounting and risk state; credentials, actor identity, time, GitHub status and verification evidence. Add a row and update its contract test whenever a new domain authority is introduced.

For a conflict, first retain both observations with their source identities and hashes. Apply a domain-specific reconciliation if the row defines one. Until then, the dependent state stays blocked/unknown. Configuration precedence (`docs/10_CONFIG_PRECEDENCE.md`) is the only general precedence ladder: SAFETY_OVERRIDE > RUNTIME > ENVIRONMENT > CONFIG_FILE > DEFAULT; equal-precedence disagreement is `CONFIG_CONFLICT` and blocks live decisions.

## Current limits

- The prompt and repository source tree are locally identifiable, but the available V4.28 recovery base does not prove byte-for-byte lineage to unavailable V4.23/V4.26 archives.
- Market-data adapters and CSV audit tooling preserve hashes and provenance metadata. No user/vendor OHLCV dataset or independent source comparison is present in this checkout; source independence, licensing, revision history, and production feed authority remain unverified.
- Several runtime authorities are durable only when explicitly connected to a persistent `EventStore`. The event store's default is in-memory, and the V2.7–V2.9 schema registry does not cover every legacy/later event stream.
- Exchange and account systems remain the external authority for actual orders, fills, balances, and venue state. Local acceptance, replay, and reconciliation ledgers record bounded copies; they do not override the venue or certify a live connection.
- Credential secret storage can use a persistent backend, but trusted service identity and reviewer identity/key provisioning are external requirements. Local test/default identity values do not establish who operated or approved a run.
- CI results describe a specific GitHub commit and run. Repository protection, trusted approval identities, independent review, and protected-main evidence require live GitHub configuration and cannot be inferred from a green test run.

## Updating the matrix

When an authority or adapter changes, update its row, implementation reference, conflict action, and boundary together. Keep external or missing sources explicitly marked; do not promote a row to a stronger status based on documentation alone. The test verifies row uniqueness, required columns, known status vocabulary, required domains, and that every cited repository file exists.

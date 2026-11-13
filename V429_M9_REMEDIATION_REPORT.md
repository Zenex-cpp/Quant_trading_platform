# V4.29 M9 Research Credential Boundary Remediation

**Status:** `TESTED`; production credential-store and process-isolation evidence remain open.

## Finding

The research credential scanner rejected direct credential types, mappings, lists and ordinary instance dictionaries, but did not inspect Python `__slots__` or NumPy object arrays. A production credential wrapped in either form passed `assert_research_safe` and could cross the research argument boundary. `TuningDataView` also accepted direct row inputs without applying that boundary itself. The credential vault itself was in-memory, so secret material could not be recovered after restart and no persistent OS backend was available.

## Changes

- Extended the scanner to inspect inherited slot declarations and Python-mangled slot names. Credential-bearing slot names and nested credential/reference/vault objects fail closed.
- Extended the scanner to traverse NumPy arrays whose dtype contains Python objects, including structured object fields. Numeric arrays remain unexpanded.
- Made direct `TuningDataView` construction validate train, validation and OOS inputs before storing them.
- Added regressions for slotted wrappers, mangled secret attribute names, NumPy object arrays, and direct tuning-data construction. Added M9 to the fixed V4.29 preflight impact set and CI workflow contract.
- Configured pytest to collect the retained legacy credential test module as part of the normal suite; historical manifests continue to reference the same path.
- Added an explicit secret-backend interface and a persistent Windows Credential Manager implementation. Production vault construction now requires a persistent backend; the in-memory backend is available only through the explicit test constructor.
- Removed raw API key/secret values from vault metadata records. The append-only ledger retains identity, validity, status, actor role and fingerprint only; active/revoked metadata is replayed from the ledger after restart.
- Resolution fetches material from the configured backend, verifies its fingerprint against the registered reference, and only then returns runtime credentials. Revocation is durable before backend deletion and retries deletion if cleanup previously failed.
- Resolution and revocation are serialized within the vault, preventing an in-flight read from being audited after a concurrent revocation; every resolution and denial receives a distinct audit event ID.
- Credential Manager target names contain only a hash-derived locator. Blob serialization is schema-checked and bounded, backend errors are sanitized, runtime credential representations redact values, and unrecognized role text is never copied into audit events.

## Verification boundary

The focused credential-backend, credential-boundary, ledger-concurrency, secret-store policy and release-contract suite passed **62 tests** on Windows/Python 3.14.4. The mandatory V4.29 runner on package 3.61.16 passed **1,306 tests, 26 skipped**, with `RELEASE_HYGIENE=PASS`; the final preflight at `.audit/V429_M9_M10_CREDENTIAL_FINAL2_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, and no blockers. A direct native Credential Manager probe returned `ERROR_ACCESS_DENIED` before any write, so the adapter tests use a synthetic API and do not validate access to the actual OS store. Deployment under a dedicated Windows service identity, process isolation from Research, and independent operational attestation remain required before M9 can be `VERIFIED`.

No production credential was configured or resolved during these tests. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

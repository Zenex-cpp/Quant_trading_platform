# V3.41 Release Notes

## M14 — No artifact execution when compatibility fails

V3.41 closes the artifact-compatibility execution boundary. A compatibility boolean is no longer sufficient to authorize deployment execution.

`CompatibilityAuthorityLedger` persists an artifact-bound compatibility authorization in the hash-chained EventStore. The authorization binds artifact hashes, code/configuration/execution-model versions and the fingerprint of the compatibility report. `INCOMPATIBLE` and `UNKNOWN` reports cannot create an authorization.

V3.28/V3.26 deployment execution paths and the V3.25 durable activation path require the same compatibility authority; a mismatched capability, artifact hash, version binding, expired authorization or invalidated dependency is fail-closed.

No external exchange/Testnet network calls or production credentials are used by this release.

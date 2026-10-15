# V3.1 Release Notes

V3.1 integrates the V3.0 Operational Truth Model into the runtime risk-taking boundary.

Added `RuntimeAuthority`, immutable `AuthorityDecision`, and `ExecutionRouter`.
Trade authorization requires fresh VERIFIED Operational Truth and requested risk not above effective risk. Deployment authorization is delegated to the canonical truth model. Decision provenance is bound to the truth state hash and deterministic input fingerprint.

No exchange network access is introduced by V3.1. Live execution remains out of scope.

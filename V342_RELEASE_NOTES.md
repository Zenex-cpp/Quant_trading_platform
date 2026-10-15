# V3.42 Release Notes

## M15 — No artifact deployment when integrity fails

V3.42 closes the artifact-integrity deployment boundary. The existing `artifacts_integrity` boolean is no longer sufficient to authorize deployment.

`ArtifactIntegrityAuthorityLedger` persists an artifact-bound integrity authorization in the hash-chained EventStore. The authority binds:

- exact expected artifact hashes;
- observed artifact hashes from the integrity verification step;
- manifest fingerprint;
- verified artifact signature;
- validity window and reviewer;
- dependency-invalidation state.

Deployment preparation, V3.25 durable activation and the final activation controller require this same authority. Missing, expired, mismatched, unsigned or dependency-invalidated integrity evidence fails closed.

No external exchange/Testnet network calls or production credentials are used by this release.

`production_ready = FALSE`

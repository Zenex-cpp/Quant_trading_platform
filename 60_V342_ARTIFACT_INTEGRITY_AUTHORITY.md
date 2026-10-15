# V3.42 Artifact Integrity Authority

M15 requires that an artifact cannot cross the deployment boundary when its integrity evidence is missing, failed, expired or invalidated.

V3.42 introduces `ArtifactIntegrityAuthorityLedger`, an append-only EventStore authority bound to the exact promotion bundle artifact hashes. Authorization additionally records the observed artifact hash set, a manifest fingerprint and explicit signature verification.

Only matching expected/observed hashes with a verified signature can issue the authority. Deployment preparation, durable activation authorization and the final activation controller require the same artifact-integrity authority identity. Hash changes, manifest changes, signature failures, expiry and dependency invalidation fail closed.

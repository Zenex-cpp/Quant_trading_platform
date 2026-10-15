# V3.41 Artifact Compatibility Authority

M14 requires that an artifact cannot cross the deployment execution boundary on the basis of a bare compatibility boolean.

V3.41 introduces `CompatibilityAuthorityLedger`, an append-only EventStore authority bound to the exact promotion bundle artifact hashes, code/configuration/execution-model versions and a fingerprinted `CompatibilityReport`.

Only an overall `COMPATIBLE` report can issue the authority. Deployment preparation, activation authorization and final V3.26 transition validation require the same durable authority identity. Missing, expired, mismatched, invalidated or incompatible compatibility evidence fails closed.

# V4.5 Change Impact

V4.5 integrates the V4.4 external-readiness revocation event with the existing dependency-invalidation authority.

The new bridge is fail-closed and does not mutate the evidence graph. It requires the revoked witness to exist as an immutable graph root, verifies the durable revocation event and exact witness/bundle/snapshot/release bindings, and records the computed blast radius through `DependencyInvalidationLedger`.

No external operational evidence is manufactured by this release.

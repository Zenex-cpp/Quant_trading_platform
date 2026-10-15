# V3.44 Release Notes

## M17 — No gate reuse after invalidating change

V3.44 closes the stale-gate reuse window after a dependency invalidation. Each critical durable gate records a dependency checkpoint sequence at issuance. `DependencyInvalidationLedger.assert_unchanged_since()` treats any later invalidation touching the gate dependency set as permanently invalidating that gate, even after the incident is subsequently revalidated. A new gate must therefore be issued after the change.

The control applies to Champion gate authorization, artifact/runtime compatibility authorization and artifact-integrity authorization. Active invalidations retain the existing fail-closed errors; historically stale gates receive explicit `*_STALE_AFTER_INVALIDATION` errors. Restart preserves the checkpoint because the checkpoint is durable evidence in the authorization event. A post-append recheck closes the concurrent invalidation window during issuance.

No external exchange/Testnet network calls or production credentials are used by this release.

`production_ready = FALSE`

# V3.44 Verification Report

Requirement: M17 — No gate reuse after invalidating change.

Status: TESTED
production_ready: FALSE

## Evidence
- `DependencyInvalidationLedger.checkpoint()` provides the durable sequence boundary at gate issuance.
- `assert_unchanged_since()` scans later dependency-invalidation events and blocks any gate whose dependency set was invalidated after issuance, regardless of later incident revalidation.
- Champion, compatibility and artifact-integrity authorizations persist the dependency checkpoint in their immutable authorization event.
- Active invalidations still block through the existing `assert_clear()` path.
- Stale authorizations receive explicit fail-closed `*_STALE_AFTER_INVALIDATION` errors.
- New authorization after revalidation receives a later checkpoint and is reusable.
- Restart test proves stale-gate blocking from a reopened EventStore.
- Post-append recheck closes the concurrent invalidation window between checkpoint capture and durable authorization append.

## Tests
- Full suite: 516 passed.
- Focused M17 suite: 5 passed.
- Focused combined regression: 26 passed.
- `compileall`: PASS.

Independent review of dependency-change orchestration remains outstanding; therefore M17 is TESTED, not VERIFIED.

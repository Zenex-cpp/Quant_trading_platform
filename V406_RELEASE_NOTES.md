# Trading Platform v4.6

## Release posture
V4.6 is an application-level governance increment built on the V4.5 package state.

## New capability
`GateRevalidationAuthorityV406` makes gate reuse explicitly dependent on dependency freshness.

A gate is `CURRENT` only when:
- its declared dependencies are clear of active invalidation; and
- no dependency invalidation has occurred after its explicit dependency checkpoint.

An impacted gate becomes `INVALIDATED`. Revalidation of the underlying incident does not resurrect the old gate: a new gate run with a new dependency checkpoint is required.

The decision is durably recorded and idempotent for the same ledger state, while later ledger events force a fresh evaluation.

## Verification
- V4.6 focused tests: 6/6 PASS;
- full regression: **973/973 PASS**;
- no Testnet or Production mutation was performed.

# Trading Platform v4.3

## Release posture
V4.3 is built from the verifiable v3.98 source base. The previously described V4.1/V4.2 source archives were not present in the current runtime; their available reports were used only as design input. This release therefore does not claim those missing source artifacts as inherited code.

## New capability
`ExternalReadinessRevalidationAuthorityV403` adds a signed revalidation witness boundary for critical production-readiness evidence.

The witness binds:
- production-critical scope;
- bundle and evidence snapshot identifiers;
- release artifact hash;
- exact hashes of the immutable EventStore events being revalidated;
- independent review evidence reference;
- reviewer/operator separation;
- reviewer key identity;
- bounded validity window;
- Ed25519 signature and signature hash.

The authority re-reads the current EventStore events, verifies their immutable event hashes and VERIFIED/REVALIDATED state, checks the EventStore chain, and records an idempotent `EXTERNAL_READINESS_REVALIDATION_ACCEPTED` event.

`assert_fresh()` hard-blocks use after witness expiry.

## Safety posture
V4.3 does not perform network access, process execution, exchange mutation, Testnet mutation, production deployment, secret handling, or external evidence fabrication.

No real external revalidation witness was produced during this release verification.

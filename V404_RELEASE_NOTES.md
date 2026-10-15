# V4.4 Release Notes

## Scope
V4.4 adds durable, signed revocation for accepted external-readiness revalidation witnesses.

## Change
`ExternalReadinessRevocationAuthorityV404` introduces an append-only revocation event bound to the exact witness fingerprint, bundle, evidence snapshot and release artifact hash. A revoked witness is fail-closed even when its original TTL has not expired.

## Guarantees
- reviewer/operator separation;
- Ed25519 signature and signature-hash verification;
- exact witness fingerprint binding;
- exact bundle/snapshot/release-hash binding;
- durable, idempotent revocation event;
- explicit `REVOKED` versus `EXPIRED` status;
- EventStore hash-chain verification;
- no network/process egress in the authority.

## Verification
- V4.4 focused tests: 5/5 PASS;
- V4.3 + V4.4 focused tests: 12/12 PASS;
- full regression: **961/961 PASS**.

## Operational statement
This release does not create or claim external operational evidence. No Testnet mutation and no Production mutation were performed.

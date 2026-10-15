# V4.6 Verification Report

## Result
PASS at the application-contract and distributed-package levels.

## Test results
- V4.6 focused: **6/6 PASS**
- full regression on source tree: **973/973 PASS**
- full regression on extracted release tarball: **973/973 PASS**

## Verified properties
1. Current gate can be reused when the dependency checkpoint is still valid.
2. A dependency invalidation after the checkpoint marks the gate `INVALIDATED`.
3. Incident revalidation does not resurrect the old gate.
4. A new gate checkpoint after successful revalidation can become `CURRENT`.
5. Same ledger state is idempotent and durably auditable.
6. The authority has no network/process egress capability by source contract.

## Package integrity
- package manifest: **1,419 entries**;
- extracted-manifest comparison: **1,419/1,419 match**;
- package-manifest SHA-256: **verified**;
- transient bytecode/cache artifacts in extracted release: **0**.

## Operational boundary
No real external operational evidence was fabricated or promoted. Production readiness remains blocked until the independent external evidence and approvals required by prior releases are materially acquired and verified.

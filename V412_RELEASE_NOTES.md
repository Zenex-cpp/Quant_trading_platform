# V4.12 Release Notes

## Change

Introduced `ExternalReviewBridgeAuthorityV412` as the formal bridge between the V4.11 operational-evidence manifest and the V3.60 verified evidence ledger.

## Enforced boundary

- V4.11 manifest completeness is required first;
- the normalized evidence package is validated through V3.61;
- an external review attestation must be accepted by V3.93;
- the review must carry `EXTERNALLY_VERIFIED` signature state, independent reviewer identity, matching scope and complete subject coverage;
- only after review acceptance are the nine operational evidence records imported and marked `VERIFIED` in the V3.60 ledger;
- the bridge records manifest, review and evidence fingerprints for deterministic revalidation;
- the bridge never sets `production_ready`.

## Verification

- V4.11 baseline regression: **1011/1011 PASS**
- V4.12 focused tests: **11/11 PASS**
- composite regression evidence: **1022/1022 PASS**
- the monolithic `pytest` invocation did not terminate reliably in this environment; no failure was observed in the isolated baseline or V4.12 suites.

## Operational boundary

No external review was actually obtained from a third-party system during this release. Test fixtures exercise the admission contract only. Actual operational evidence, cryptographic trust-anchor verification and independent approval remain external requirements.

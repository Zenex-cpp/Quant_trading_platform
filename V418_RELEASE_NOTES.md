# V4.18 Release Notes

## Change

Added `MachineCheckReadinessAuthorityV418` for Master Prompt §177 mandatory machine checks M1–M30.

## Enforced boundary

- requires one and only one row for every M1–M30 check and the full compliance-matrix column set;
- preserves the Master Prompt's normative requirement text and allowed status vocabulary;
- blocks a check unless status is `VERIFIED`, required references exist, `review_reference` matches the accepted review and `unresolved_gap` is empty;
- requires an upstream durable V4.17 compliance decision for the same bundle;
- requires a durable V3.93 external-review acceptance for the exact `MP177-{bundle_id}` package with complete M1–M30 evidence coverage;
- requires the V4.13 cryptographic review gate, bound to the same package hash, review hash and bundle through the V3.94/V3.95 chain;
- binds package evidence content hashes to the canonical matrix rows;
- persists a fingerprinted, immutable and idempotent decision; changed inputs cannot reuse the same decision ID;
- never enables runtime activation and never changes `production_ready` to true.

## Current state

The supplied compliance matrix is intentionally blocked. It has 30 rows: 27 `TESTED`, 2 `IMPLEMENTED`, and 1 `PARTIAL`; all rows retain unresolved gaps, all `review_reference` values are empty, and `schema_reference` values are blank where a schema mapping was not provided. Those are not promoted to `VERIFIED` by this release.

## Verification

- V4.18 focused tests: **15/15 PASS**.
- Full repository regression: **1,066/1,066 PASS**.
- The same full suite is required to pass again on the frozen archive extraction before release integrity is claimed.
- Application test success does not represent an independent external M1–M30 review or production readiness.

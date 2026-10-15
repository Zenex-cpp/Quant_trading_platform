# V4.5 Verification Report

## Pre-change baseline
- V4.4 full regression: 961/961 PASS.

## V4.5 focused verification
- V4.5 focused tests: 6/6 PASS.
- V4.4 + V4.5 focused tests: 11/11 PASS.

## Full regression
- Full suite on source tree: **967/967 PASS**.

## As-shipped verification
- Archive: `trading_platform_v4_5.tar.gz`.
- Manifest entries: **1,410**.
- Manifest checksum verification: **OK**.
- Extracted archive contents: **1,410/1,410** manifest match.
- Archive hygiene before extraction: no `.pyc`, `__pycache__` or `.pytest_cache` files.
- Full regression on extracted archive: **967/967 PASS**.
- Archive SHA-256: `d1940c57df1d69071132618daf28b77a0e5ca63e90135f8d39fddecf6402fb85`.

## Integrity controls
- shared EventStore enforced;
- hash-chain verified before and after dependency invalidation;
- durable V4.4 revocation required;
- exact witness/bundle/snapshot/release bindings rechecked;
- witness must exist as dependency-graph root;
- invalidation persistence is idempotent.

## Operational boundary
No Testnet or Production mutation occurred. No external operational evidence was fabricated.

## Readiness
Production readiness remains `NOT_VERIFIED` / blocked by external evidence gaps.

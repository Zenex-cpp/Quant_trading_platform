# V3.6 Verification Report

Date: 2026-09-13

## Result
- Full test suite: **255 passed**
- Testnet execution boundary tests: **PASS**
- User stream correlation/deduplication tests: **PASS**
- Ambiguous-submit no-blind-retry test: **PASS**
- REST-filled-without-trade-evidence safety test: **PASS**
- Live exchange calls: **NOT RUN**
- Credentials used: **NONE**
- Production readiness: **FALSE**

## Critical invariants exercised
1. `clientOrderId` cannot map to multiple intents.
2. `exchangeOrderId` cannot map to multiple intents.
3. Client and exchange correlation disagreement fails closed.
4. Replayed identical user events do not duplicate accounting.
5. A transport-ambiguous submit never triggers an automatic second POST.
6. Reconciliation proceeds through the same correlation key and requires an open UNKNOWN case.
7. REST `FILLED` status alone does not synthesize a trade/fill record.
8. A REST `FILLED` status with executed quantity greater than accounted trade quantity remains `UNKNOWN` until trade-level evidence closes the gap.

## Package verification
The release tarball is re-extracted into a clean directory and the complete test suite is rerun there before release. The SHA-256 is recorded in the accompanying `.sha256` file.

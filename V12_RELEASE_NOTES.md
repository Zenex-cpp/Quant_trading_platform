# Trading Platform V1.2 — Release Notes

## Status
TESTED / NOT VERIFIED / NOT PRODUCTION READY.

## Delivered
- Testnet-only client boundary with explicit environment guard.
- HMAC-SHA256 signing primitive with credentials supplied at call time and never retained by the client object.
- Deterministic evidence hashing that excludes the hash field itself.
- 11 mandatory verification scenarios; 10 require live testnet evidence.
- Offline verification harness that never promotes to production-ready state.
- Compliance V1.2 and evidence documentation.
- Current Binance documentation references captured for the adapter contract.

## Verification limitation
No live testnet account/session evidence is present in the workspace. Therefore TN-01..TN-10 remain NOT_VERIFIED. This is intentional and is not converted into a synthetic PASS.

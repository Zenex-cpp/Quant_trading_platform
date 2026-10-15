# V1.3 Release Notes

V1.3 adds a TESTNET-only live verification runner and evidence writer on top of V1.2.

## Status

`TESTED / NOT VERIFIED / NOT PRODUCTION READY`

No live Binance session was executed during the build because no operator-provided testnet credentials/session were present. This is deliberate and prevents synthetic evidence from being misrepresented as exchange evidence.

## New components

- `trading_platform.testnet.runner`
- environment-driven TESTNET runner configuration
- runtime credential injection
- signed request execution through the existing client boundary
- scenario-result evidence artifacts and hashes
- explicit production-readiness false invariant
- V1.3 contract registry
- operator CLI entrypoint

## Verification boundary

The runner can produce evidence only after a real testnet session. Until then TN-01..TN-10 remain `NOT_VERIFIED`; TN-11 remains offline-contract-testable.

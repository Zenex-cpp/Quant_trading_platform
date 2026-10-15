# V3.89 First Testnet Credential Runbook

This runbook authorizes credential acquisition only. It does not authorize a mutation by itself.

## Hard prerequisites

- TESTNET environment
- exact Testnet REST endpoint configured
- dedicated `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_API_SECRET`
- no production credential environment variable present
- V3.83 connectivity VERIFIED
- V3.84 activation ACTIVE
- V3.86 operator session READY
- V3.87 first-order preparation ARMED
- V3.88 evidence bundle OPEN and complete through the pre-trade boundary

## Credential capability sequence

1. Acquire dedicated Testnet credential material only at runtime.
2. Compute an opaque credential fingerprint in memory.
3. Issue one Testnet capability with a short TTL.
4. Revalidate the exact Testnet endpoint immediately before release.
5. Consume the capability exactly once.
6. Hand the resulting runtime credential values to the already-authorized V3.87/V3.85 submit path.
7. On UNKNOWN, stop new risk. Do not reissue a credential capability merely to retry.
8. Close the V3.88 evidence bundle only after order, user-data, reconciliation and accounting evidence are GREEN.

## Forbidden

- mainnet/prod credential variables in the execution environment
- raw credentials in logs, evidence, manifests or audit events
- capability reuse
- endpoint substitution
- execution from a non-ARMED V3.87 runner
- blind retry after an uncertain transport outcome

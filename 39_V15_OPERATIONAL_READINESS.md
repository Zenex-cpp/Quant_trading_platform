# V1.5 — Operational Readiness Gate

## Purpose
V1.5 converts the V1.3/V1.4 testnet runner into a controlled operational-readiness boundary.

## New machine-checkable contracts
- TESTNET-only network allowlist.
- TLS-only transport.
- Mainnet host denial.
- Runtime-only secret usage.
- RPO/RTO and backup-frequency contract.
- Recovery proof = state_reconciled AND invariants_pass AND no_unresolved_critical_issue AND guards_pass.
- Production-readiness gate fails closed when any blocking item is not PASS.

## Testnet client
The stdlib client supports read-only connectivity and exchangeInfo probes, plus a signed account probe when credentials are injected at runtime. It never stores or serializes the API secret.

The client defaults to `https://testnet.binancefuture.com`; this endpoint is an external-reference parameter and must be revalidated against the current Binance environment before an operational session. Binance documentation records the Futures Testnet WebSocket base URL `wss://fstream.binancefuture.com`; REST endpoint selection remains a versioned external reference rather than a core-domain constant.

## Production boundary
V1.5 does not mark production readiness from software tests alone. Real Testnet evidence, infrastructure isolation, restore evidence, monitoring, security review and human approval remain mandatory.

# V1.3 — Live Testnet Evidence Runner

## Purpose
V1.3 adds a credential-at-runtime, TESTNET-only evidence runner. The package does not contain credentials and does not execute a live session during build/test.

## Safety boundary
The runner refuses non-TESTNET environments, requires TLS, blocks obvious Binance mainnet hosts, and keeps credential values out of configuration objects and evidence artifacts.

## Evidence rule
A testnet scenario is not `VERIFIED` merely because the runner can issue a request. Verification requires raw response/event evidence, endpoint/environment identity, correlation, pre/post snapshots where applicable, hashes, reconciliation closure, invariants, owner/reviewer and timestamps.

## Execution
Credentials must be injected at runtime. No API key or secret is committed to the repository. The base REST and WebSocket URLs are environment-configurable so a venue endpoint is not hard-coded when an official environment reference is not yet independently captured in the project.

Expected environment variables:

- `BINANCE_TESTNET_BASE_URL`
- `BINANCE_TESTNET_WS_URL` (optional until WebSocket runner is enabled)
- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`
- `BINANCE_TESTNET_SYMBOL` (default `BTCUSDT`)

The runner is intentionally not a production client. It is a verification harness.

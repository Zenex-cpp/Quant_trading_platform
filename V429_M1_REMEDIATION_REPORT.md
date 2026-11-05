# V4.29 M1 Testnet Read-Only Boundary Remediation

**Status:** `TESTED`; independent review and live venue evidence remain open.

## Changes

- `BinanceTestnetClient`, `SessionConfig`, and `RunnerConfig` now reject endpoints outside the shared Testnet host allowlist.
- The legacy `LiveTestnetSession.run_probe` and `LiveTestnetEvidenceRunner.run_signed_query` only accept canonical `GET` requests. POST, PUT, PATCH, and DELETE requests fail before transport invocation.
- Request targets cannot supply an alternate authority, embedded query, fragment, or control characters. Query parameters remain passed separately.
- The guarded `BinanceTestnetExecutionGateway` remains the route for Testnet order submission and cancellation.

## Verification

The focused Testnet boundary and existing session/client tests pass. The tests confirm that order-submission attempts and mainnet endpoints are rejected before a transport call. No exchange request or order was sent.

M1 remains `TESTED`, not `VERIFIED`; independent review and live venue evidence are still required. This remediation does not establish production readiness or authorize LIVE trading.

`external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

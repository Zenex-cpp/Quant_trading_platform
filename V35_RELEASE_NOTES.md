# V3.5 Release Notes

V3.5 collega il livello `ExecutionBridge` al boundary Binance USDⓈ-M Testnet mantenendo il core privo di I/O implicito.

## Runtime contract
- Environment: `TESTNET` only.
- Base URL: configurable; default `https://testnet.binancefuture.com`.
- TLS required.
- Network allowlist enforced before construction.
- Runtime credentials are supplied per operation and not retained by the gateway.
- Mutating/query endpoints use `/fapi/v1/order`.
- `newClientOrderId` is deterministic input from the authorized `OrderRequest`.
- Query and cancel correlate through `origClientOrderId`.

## Safety behavior
- Transport exception on submit => `ExchangeUncertain`, never implicit retry.
- Unknown exchange status => `UNKNOWN`.
- Resolution path is query/reconciliation, not blind resend.
- Unknown query/cancel outcomes remain non-authoritative.
- Mainnet/non-TLS configuration fails closed.

## Verification
- Full regression: 248 passed.
- No exchange credentials used.
- No exchange network I/O performed.
- No live/Testnet mutation performed.

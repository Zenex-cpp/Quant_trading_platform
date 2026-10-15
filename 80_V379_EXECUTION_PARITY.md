# V3.79 — Execution Seam Parity & Testnet Boundary

## Scope

V3.79 extends §85/§86 from decision-stage parity to the execution seam.
The shared decision chain remains the single producer of `OrderIntent`; the
live/shadow side consumes the same intent contract through an injected adapter.

## Implemented

- Backtest venue execution + decision trace capture using the V3.78 venue model.
- Live/shadow decision run over the same market-event sequence and supplied
  position state.
- Intent fingerprint comparison at every event boundary.
- Adapter observation normalization with deterministic evidence hashing.
- Testnet mutation gate, disabled by default and requiring explicit operator
  approval plus a hard notional ceiling.
- Read-only Binance USDⓈ-M Testnet probe for `/fapi/v1/time` and
  `/fapi/v1/exchangeInfo`.
- MARKET `OrderIntent → OrderRequest` adapter mapping with deterministic client and
  idempotency identifiers.
- Network-policy enforcement preventing accidental mainnet use.

## Explicit limits

- The parity runner submits no real order.
- Testnet public probe is read-only.
- Full testnet user-data WebSocket parity is not yet demonstrated here.
- This runtime could not resolve the external Testnet host during the v3.79
  public probe, so live connectivity evidence remains `NOT_VERIFIED`.
- The legacy `OrderRequest` cannot yet express the complete V3.78 limit-order
  contract (`price`, `timeInForce`); such testnet limit submission is therefore
  intentionally left OPEN and fail-closed.
- No claim of production exchange matching-engine or latency parity.

## External venue reference

Current official Binance documentation describes signed endpoints using
HMAC-SHA256 and timestamp/`recvWindow` timing checks, while current USDⓈ-M
WebSocket documentation describes 24-hour connection lifetime, ping/pong
requirements, and recommends WebSocket user-data state for order/position
monitoring. These facts remain adapter-level references and are not leaked into
venue-agnostic core contracts.

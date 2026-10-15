# Trading Platform v3.84 — Release Notes

## Scope

v3.84 introduces the **Testnet Execution Activation Authority**, the missing safety boundary between the v3.83 read-only connectivity proof and any future Testnet mutation.

Activation requires all of the following, simultaneously:

1. `ConnectivityProofV384.status = VERIFIED`.
2. Connectivity evidence hash is present and the proof window is still valid.
3. Connectivity endpoint passes the Testnet network policy.
4. Client/server clock skew is inside the hard limit.
5. Explicit operator approval with scope `TESTNET_ORDER_MUTATION`.
6. Operator approval is unexpired.
7. Reconciliation state is exactly `GREEN`.
8. Activation TTL is bounded by the shortest of authority TTL, connectivity proof TTL and operator approval TTL.
9. Symbol is inside the allowlist.
10. Requested notional is below the absolute Testnet ceiling.

## Operational semantics

Activation states are orthogonal to the rest of the platform:

- `INACTIVE`
- `ACTIVE`
- `HALTED`
- `EXPIRED`

`HALTED` and `EXPIRED` block new risk immediately. `deactivate()` revokes the activation and clears runtime bindings.

## Credential boundary

Credentials are supplied only to the final gateway call. The activation authority never stores API keys/secrets and audit events do not serialize credential values.

## Kill switch

`halt(reason)` is a one-way local safety action for the current activation. A new activation requires a new valid connectivity proof, operator approval and green reconciliation.

## Scope limits

v3.84 does not claim real Testnet execution. The current environment still reports `NOT_VERIFIED` for public Testnet connectivity because DNS resolution is unavailable. No mutating Testnet API call was made.

`production_ready = FALSE`.

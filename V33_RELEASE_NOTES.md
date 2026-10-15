# V3.3 RELEASE NOTES

## Scope
Execution commit boundary: idempotency, order lifecycle and reconciliation are now one coordinated safety path.

## Guarantees
- Exact intent payload is fingerprinted before commit.
- Capability validation is pure; consumption happens only after deterministic request construction succeeds.
- One capability can create at most one committed OrderRequest.
- Idempotent duplicate commits return the previously committed request.
- UNKNOWN position/order state never dispatches a new request; it raises `UNKNOWN_ORDER_REQUIRES_RECONCILIATION` and creates a reconciliation case.
- Blind retry remains forbidden while an UNKNOWN case is open.
- Lifecycle advances to `SUBMITTED` only at the commit point.
- No exchange/network side effect occurs in the coordinator itself.

## Verification
The offline regression suite is the release gate. Live/Testnet execution is not claimed by this release.

# V3.89 Change Impact

## Safety

Strengthens M9 and M25/M30 style boundaries for runtime execution credentials by preventing an undifferentiated credential blob from silently crossing into the first Testnet mutation path.

## Execution

No change to the V3.85 controlled-submit transport contract. V3.89 adds an authorization layer that can release runtime credentials only once and only for the exact Testnet REST host.

## Evidence

Only the opaque capability id, credential fingerprint, scope, source, endpoint host and validity window are evidence-safe metadata. Raw key/secret material remains process-local and ephemeral.

## Failure mode

Any ambiguity about credential source, production credential presence, endpoint, TTL, or repeated use results in fail-closed rejection.

## External status

No real Testnet mutation is performed by the V3.89 verification runner. External execution remains unverified until the runtime has working connectivity and dedicated Testnet credentials.

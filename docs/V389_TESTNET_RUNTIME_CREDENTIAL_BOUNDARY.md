# V3.89 Testnet Runtime Credential Boundary

## Objective

Prevent the first Testnet mutation from consuming an undifferentiated runtime credential object.

## Required properties

`TESTNET scope + dedicated credential source + exact Testnet endpoint + unexpired TTL + one-shot capability -> credential release`

## Dedicated source

Only these environment variables are accepted:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

Presence of any known production credential variables is a hard block.

## Secret handling

Credentials remain process-local. The capability metadata contains no raw credential material. The capability repr is intentionally safe. The evidence layer receives only opaque identifiers, hashes, scope and time-bounded metadata.

## One-shot behavior

The capability is consumed immediately before the mutating/query operation and cannot be consumed twice. A transport-uncertain outcome therefore does not create a retry capability.

## Endpoint binding

Credential release is valid only for `https://testnet.binancefuture.com`. Endpoint mismatches fail before the secret material is released to the caller.

## Verification stance

The release runner only checks capability issuance rules. It does not call the exchange and does not attempt an order.

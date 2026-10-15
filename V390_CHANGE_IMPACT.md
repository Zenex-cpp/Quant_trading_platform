# V3.90 Change Impact

## Safety

Strengthens the Testnet execution perimeter by preventing credentialed requests from
silently inheriting process proxy configuration or following an HTTP redirect.

## Network

The runtime transport uses an empty `ProxyHandler`, requires the exact HTTPS Testnet
REST host, and rejects redirects. WebSocket endpoint authorization remains explicit
and uses the separate Testnet WebSocket allowlist.

## Execution

The V3.90 Binance gateway is compatible with the existing V3.80 order adapter and
therefore can be injected into the existing controlled-submit path without creating
a second mutation authority.

## Evidence

The egress authority emits only safe policy metadata. Proxy values, credentials and
raw response bodies are not persisted by the V3.90 authority itself.

## External status

No real Testnet mutation is performed by this release. Production readiness remains
FALSE until real authenticated Testnet evidence is observed and independently reviewed.

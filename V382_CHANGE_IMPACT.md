# V3.82 Change Impact

Changed component: authenticated Testnet user-data session boundary.

Affected components:
- Binance USER_STREAM control
- private user-data WebSocket transport
- user-data projection/reconciliation gate
- Testnet network policy

Historical artifacts: no modification to v3.73-v3.81 historical evidence or immutable release archives.

New behavior:
- explicit authenticated session state;
- control-plane start/ping/stop;
- private stream lifecycle;
- listen-key rotation;
- fail-closed expiry/error handling.

Production impact: none. No production hosts are permitted by the Testnet session configuration.

Revalidation trigger:
- Binance USER_STREAM protocol change;
- private WebSocket route change;
- Testnet environment endpoint change;
- user-data event schema change;
- credential policy change.

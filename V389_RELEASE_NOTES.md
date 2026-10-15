# V3.89 Release Notes

V3.89 adds a one-shot runtime Testnet credential capability above the V3.88 evidence-closed boundary.

The capability binds credential use to:

- TESTNET scope;
- dedicated `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` environment source;
- the exact allowed Testnet REST host;
- a bounded runtime TTL;
- an opaque key fingerprint;
- one-shot consumption.

The authority refuses to issue a Testnet capability when production credential environment variables are present. Secret values are never part of capability metadata, repr output, evidence payloads or audit artifacts.

V3.89 remains probe-only. It does not submit an exchange mutation during release verification.

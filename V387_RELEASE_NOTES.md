# V3.87 Release Notes

V3.87 adds the first-order Testnet safety layer above V3.86.

Main change: the first Testnet order must be `LIMIT + GTC`, use `BTCUSDT`, remain within the hard notional ceiling, and be provably non-marketable against a fresh bid/ask snapshot. Quote staleness becomes a normal machine-checkable BLOCK rather than an unhandled exception.

The observation layer enforces client-order correlation, pre-submit exclusion, monotonic event time, and terminal-state recognition including `EXPIRED_IN_MATCH`.

No real Testnet mutation is performed by the release verification runner.

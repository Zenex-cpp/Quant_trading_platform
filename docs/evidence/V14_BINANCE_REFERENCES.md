# V1.4 Binance References

Current official Binance documentation was reviewed for the adapter boundary and user-data behavior on 2026-09-11.

The project must register the exact Testnet endpoints effective at execution time rather than infer them from mainnet documentation. The implementation therefore requires `BINANCE_TESTNET_BASE_URL` and `BINANCE_TESTNET_WS_URL` to be explicitly configured.

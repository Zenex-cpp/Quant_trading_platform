# V3.90 Binance References

Current endpoint details must be revalidated at execution time against official Binance
USDⓈ-M documentation. V3.90 itself does not hard-code a production endpoint and blocks
all hosts outside the approved Testnet scope.

Reference families:

- Binance USDⓈ-M derivatives API documentation
- Binance USDⓈ-M derivatives change log

The code-level boundary intentionally remains stricter than a generic Binance hostname
allowlist: the credentialed REST path is exact-host Testnet only.

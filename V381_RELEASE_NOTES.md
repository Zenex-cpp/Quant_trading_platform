# V3.81 Release Notes

- Added deterministic end-to-end Testnet acceptance harness.
- Added full local chain: Intent -> Request -> simulated ACK -> ORDER_TRADE_UPDATE -> ACCOUNT_UPDATE -> REST/WS reconciliation -> FillLedger -> PositionLedger -> Accounting.
- Added duplicate-trade no-double-count evidence.
- Added deliberate reconciliation mismatch negative-path evidence.
- Added read-only live Testnet preflight.
- Automated verification: **755/755 PASS**; V3.81 targeted: **5/5 PASS**.
- Live Testnet public preflight: **NOT_VERIFIED** due runtime DNS resolution failure.
- No real mutating Testnet order was executed by the release runner.
- Production remains blocked.

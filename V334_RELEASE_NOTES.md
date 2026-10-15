# V3.34 Release Notes

## Scope
M7 — `No Champion without required gates`.

## Enforcement
- Added durable `ChampionGateAuthorityLedger`.
- Champion authority requires all required gates to be passed.
- Authority is bound to model id/version, candidate, promotion id and validity window.
- Dependency invalidation blocks Champion authority reuse.
- Event-store integrity is checked and authority survives restart.
- `ChampionChallengerRegistry.promote()` now requires durable Champion gate authority.
- LIVE deployment activation requires a valid Champion gate authorization; missing or invalid authority fails closed.

## Safety
No Binance/Testnet network request was made. No real credentials were used. No live trading was attempted.

`production_ready = FALSE`

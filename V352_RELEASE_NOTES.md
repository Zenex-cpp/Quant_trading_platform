# V3.52 Release Notes — M25

## Requirement
**M25 — Research network cannot reach production trading endpoints.**

## Implementation
- Added `ResearchNetworkPolicy` with an empty allowlist by default.
- Added fail-closed `assert_research_endpoint_allowed` helper.
- Production Binance trading hosts and Binance production-domain suffixes are rejected both at policy construction and at endpoint decision time.
- Research policy configuration cannot include production trading hosts.
- Added a static network-surface guard over `trading_platform/research/` that rejects direct HTTP/socket client imports, `urlopen`, and production trading endpoint literals.
- Mirrored network-policy changes under `src/trading_platform`.

## Safety Boundary
The Research domain has no default egress route. Explicit non-production egress is opt-in through an allowlist; production trading endpoints are structurally non-configurable.

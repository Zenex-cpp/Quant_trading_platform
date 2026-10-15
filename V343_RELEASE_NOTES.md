# V3.43 — M16 Configuration Conflict Authority

M16 is enforced at the canonical Operational Truth / Runtime Authority boundary.

## Changes
- Added `trading_platform.v343.config_authority.ConfigurationAuthorityLedger`.
- Equal-precedence conflicting configuration values are durably recorded as `CONFIG_CONFLICT` without persisting raw configuration values.
- `OperationalTruth` now carries configuration status and configuration fingerprint in its canonical state hash.
- `RuntimeAuthority` fail-closes LIVE TRADE and LIVE DEPLOY decisions on `CONFIG_CONFLICT` or unknown configuration status.
- Existing CANARY behavior is unchanged.
- Added focused M16 tests for direct authority, router path, durable conflict audit, resolved path and restart persistence.

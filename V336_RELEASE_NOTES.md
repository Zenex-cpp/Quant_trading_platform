# V3.36 Release Notes

## Scope
M9 — No Production credential visibility from Research.

## Implemented
- Added an auditable production credential vault with opaque versioned references.
- Production secret material is retained only in the runtime vault; it is never written to EventStore payloads, metadata, or logs produced by the vault.
- Credential resolution is restricted to the `PRODUCTION_TRADING` role and fails closed for Research.
- Credential registration/rotation/revocation is restricted to `SECURITY_ADMIN` or `PRODUCTION_TRADING`.
- Credential references are time-bounded, versioned, fingerprinted, revocable, and audited.
- Added a Research credential boundary that rejects production credential material, references, vaults, and credential-bearing mappings/objects.
- Wired the boundary into `TuningSession` construction, evaluator arguments, and `fit_on_train_only`.
- Mirrored security/research changes under `src/trading_platform`.
- Packaging version aligned to `3.36.0`.

## Non-goals
No live trading, no Binance/Testnet requests, no real production credential use.

## Compliance
M9 = TESTED, not VERIFIED. Independent review and operational secret-store evidence remain required by the Master Prompt.

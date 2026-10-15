# V3.49 Verification Report

Requirement: M22 — Worse liquidity cannot increase allowed exposure.

Implementation:
- `trading_platform/v349/liquidity_risk_authority.py`
- `trading_platform/v349/liquidity_registry.py`
- `trading_platform/v31/authority.py`
- `trading_platform/v318/durable_decision.py`
- `trading_platform/risk/monotonicity.py`
- `trading_platform/portfolio/capacity.py`
- mirrored V3.49 package under `src/trading_platform/`

Evidence:
- higher liquidity stress cannot authorize higher risk;
- LIVE runtime applies the liquidity-adjusted risk cap before trade authorization;
- combined uncertainty + liquidity uses the tightest cap;
- unregistered liquidity method/version fails closed;
- durable risk decisions reject allowed exposure above the liquidity cap;
- restart replay preserves liquidity provenance;
- a durable risk decision becomes stale when current liquidity stress changes;
- `adjusted_risk()` derives liquidity factor from the production mapping and rejects upward overrides;
- capacity monotonicity prevents worsening liquidity capacity from increasing capacity;
- focused M22 suite: 8 passed;
- full suite: 559 passed;
- `compileall`: PASS.

Status: TESTED, not VERIFIED. Independent review of the liquidity-method registry and full production liquidity/utilization calibration remains outstanding.

`production_ready = FALSE`.

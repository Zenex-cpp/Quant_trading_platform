# V3.49 Release Notes

## M22 — Worse liquidity cannot increase allowed exposure

V3.49 chiude il gap tra le primitive di liquidità/capacity già presenti e il decision boundary di produzione.

La nuova `LiquidityRiskAuthority` registra method/version e trasforma un `liquidity_stress` crescente in un `risk_factor` non crescente. Il registry production contiene `CONSERVATIVE_LINEAR/1`: `risk_factor=max(floor, 1-min(1, liquidity_stress/max_stress))`.

Il runtime `RuntimeAuthority` applica il liquidity-adjusted risk come hard cap per `TRADE` in LIVE. Quando sono presenti anche uncertainty e liquidity, il cap effettivo è il minimo dei due cap. Un rischio richiesto superiore al cap viene rifiutato con `RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK`.

`adjusted_risk()` deriva il liquidity factor dal mapping registrato e non accetta un fattore superiore a 1. `DurableRiskDecisionLedger` persiste liquidity stress, method/version e risk factor, impedisce `allowed_exposure` sopra il cap e rende stale una decisione quando la liquidità osservata cambia.

`estimate_capacity()` resta conservativa rispetto a un peggioramento della capacità di liquidità ed espone una primitive di monotonicità esplicita.

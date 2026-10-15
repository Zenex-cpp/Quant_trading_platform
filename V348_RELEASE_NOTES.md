# V3.48 Release Notes

## M21 — Higher uncertainty cannot increase risk

V3.48 chiude il gap tra la primitive di monotonicità già esistente e il decision boundary di produzione.

La nuova `UncertaintyRiskAuthority` calcola un `risk_factor` conservativo e registra method/version. Il registry production contiene il solo mapping autorizzato `CONSERVATIVE_LINEAR/1`: `risk_factor=max(floor, 1-min(1, uncertainty/max_uncertainty))`.

Il runtime `RuntimeAuthority` applica il risultato come hard cap per il rischio LIVE. Un rischio richiesto superiore al cap uncertainty-adjusted viene rifiutato con `RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK`.

`adjusted_risk()` non accetta più un `uncertainty_factor > 1` e, quando viene fornita `uncertainty`, deriva il factor dal mapping registrato. `CapabilityAuthority` e `ExecutionRouter` propagano la stessa provenance.

`DurableRiskDecisionLedger` può ora registrare uncertainty, method/version e risk factor; la validation impedisce `allowed_exposure` sopra il cap uncertainty-adjusted e rende stale una decisione se l'uncertainty osservata cambia.

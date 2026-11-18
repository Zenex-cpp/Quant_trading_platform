# V3.48 Release Notes

## M21 — Higher uncertainty cannot increase risk

V3.48 chiude il gap tra la primitive di monotonicità già esistente e il decision boundary di produzione.

La nuova `UncertaintyRiskAuthority` calcola un `risk_factor` conservativo e registra method/version. Il registry production contiene il solo mapping autorizzato `CONSERVATIVE_LINEAR/1`: `risk_factor=max(floor, 1-min(1, uncertainty/max_uncertainty))`.

Il runtime `RuntimeAuthority` applica il risultato come hard cap per il rischio LIVE. Un rischio richiesto superiore al cap uncertainty-adjusted viene rifiutato con `RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK`.

`adjusted_risk()` non accetta più un `uncertainty_factor > 1` e, quando viene fornita `uncertainty`, deriva il factor dal mapping registrato. `CapabilityAuthority` e `ExecutionRouter` propagano la stessa provenance.

`DurableRiskDecisionLedger` può ora registrare uncertainty, method/version e risk factor; la validation impedisce `allowed_exposure` sopra il cap uncertainty-adjusted e rende stale una decisione se l'uncertainty osservata cambia.

## M21 source binding and calibration gates — package 3.61.21

Il metodo `CONSERVATIVE_LINEAR/1` resta l'unico moltiplicatore di rischio production registrato. Il registry documenta fonte, definizione, bounds, soglia, azione, monitoraggio e stato di eleggibilità per la misura dichiarata dal signed model, Bernoulli entropy e dispersione d'ensemble. Le ultime due restano sperimentali.

La valutazione di rischio LIVE richiede che la misura venga da una `Prediction` legata all'hash dell'artefatto firmato e che `OperationalTruth.model_output` includa hash e fingerprint dell'assessment. Scalar uncertainty senza provenienza viene negata. Authority, router, capability monouso, ledger durevole e final dispatch conservano e ricontrollano identità, fingerprint e TTL. Lo stato `calibration_state` del manifest firmato è metadato e non prova la calibrazione: senza un `CalibrationReport` separato l'assessment forza `UNKNOWN` e applica il cap 0.25. Report, fonti corrente/riferimento, sample size, metriche, drift e soglie entrano nel fingerprint dell'assessment.

Gli stati `UNKNOWN` e `POOR` limitano il fattore al massimo a 0.25; `ACCEPTABLE` al massimo a 0.50. La calibrazione calcola Brier, ECE, reliability bins e drift rispetto a una finestra di riferimento distinta; senza ID fonte, riferimento o almeno 30 osservazioni per finestra lo stato è `UNKNOWN`.

M21 resta `TESTED`: mancano ablation multiplier ON/OFF su dati reali, soglie calibrate per venue/regime, fonte indipendente verificata e review esterna. Il fingerprint del report non è una firma e non autentica dataset o produttore; gli stati sintetici e l'hash di artefatto nei fixture non dimostrano tali evidenze.

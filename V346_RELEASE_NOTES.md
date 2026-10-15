# V3.46 Release Notes

## M19 — No promotion without valid Promotion Bundle

V3.46 introduce una `PromotionBundleAuthorityLedger` durevole. La promotion non può attraversare il control plane con il solo oggetto `PromotionBundle` in memoria: serve una authority persistita che identifichi esattamente il bundle validato, tramite fingerprint canonico dei contenuti e dependency checkpoint.

La authority è restart-safe, fail-closed su tamper, binding mismatch, expiry e invalidazione successiva delle dipendenze. Anche i percorsi Champion e deployment legacy verificano la stessa authority.

Inoltre il legacy promotion checker (`trading_platform/evidence/promotion_checks.py`) richiede ora la stessa durable Promotion Bundle Authority e non può più promuovere con il solo booleano `bundle_complete`.

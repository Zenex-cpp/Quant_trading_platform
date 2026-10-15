# V0.3 Completion Contract

V0.3 closes the data-foundation gaps needed before V0.4 ML. It provides deterministic dataset audit, PIT/leakage scanning, chronological splits with purge/embargo primitives, final-holdout access control and an immutable-friendly lineage graph.

## Controls
- OHLCV semantic validation: timestamps, finite numerics, OHLC ordering, non-positive prices, negative volume.
- Chronological split: TRAIN / VALIDATION / OOS / FINAL_HOLDOUT.
- Purge based on label horizon and optional embargo.
- Central leakage scan emitting `LeakageFinding` objects and a blocking result for critical findings.
- Final holdout tuning access is denied by policy and intended to be access-logged externally.
- Lineage nodes require upstream dependencies and cannot be mutated in-place.

## Remaining gap before V0.4 production-grade research
A real DATASET-01 fixture must be ingested and audited with the same contracts; feed adapters remain external to this package. Full statistical CPCV/cross-fitting and exchange-specific order-book semantics remain later increments where applicable.

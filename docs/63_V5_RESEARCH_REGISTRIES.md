# V5.0 Statistical, Metric, Objective, and Benchmark Registries

Machine-readable registries are:

- schemas/v5_metric_applicability_registry.csv
- schemas/v5_objective_function_registry.csv
- schemas/v5_benchmark_registry.csv

## Interpretation

Every row is SPECIFICATION_ONLY. It records required inputs, applicability limits, and pre-registration rules; it does not assert empirical validation or authorize production use. No numeric performance threshold is introduced by these registries.

Metric choice must match the target, data availability, sampling convention, and evidence scope. The Brier and ten-bin calibration entries follow the registered V0.4 calibration contract. Drawdown requires source-bound accounting history. Net P&L requires a reconciled event-sourced ledger with costs preserved as separate components.

An objective function may rank candidates only after hard constraints and mandatory gates pass. Formula, sample window, estimator, costs, and constraints must be frozen before results are inspected. Final Holdout remains unavailable to tuning.

Benchmarks must be selected before candidate results are inspected and must use comparable point-in-time coverage and cost treatment. A benchmark is not a production-readiness test. If no defensible comparison exists, record BENCHMARK-NONE and make no relative-performance promotion claim.

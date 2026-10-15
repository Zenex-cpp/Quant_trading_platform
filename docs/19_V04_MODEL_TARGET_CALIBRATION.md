# V0.4 — Target, Model, Calibration & Uncertainty Foundation

## Scope
V0.4 implements the minimal AI Model Lab needed before model complexity expands. It adds versioned target contracts, auditable model wrappers, prediction contract, artifact pre-load checks, calibration diagnostics and uncertainty measures.

## Safety boundaries
- Research/backtest only.
- RL remains EXPERIMENTAL and is not implemented here.
- No automatic promotion or deployment.
- Higher uncertainty can only reduce or preserve the risk factor.
- Model execution requires explicit schema/version/integrity compatibility.

## Target semantics
Target labels are available at `label_end`; the label is not available at entry time. The target generator therefore integrates with the V0.3 PIT contract rather than making future outcomes visible to features.

## Baselines
The initial model registry contains only logistic regression and a shallow decision tree. Complexity is intentionally constrained until ablation and robustness evidence justify expansion.

## Calibration
Calibration is diagnostics-first: Brier score, expected calibration error and a calibration state. Thresholds are configurable research parameters and must be registered before evaluation.

## Uncertainty
Supported measures: Bernoulli entropy and ensemble dispersion. `conservative_risk_factor()` enforces a monotonic mapping where more uncertainty cannot increase risk.

## Required evidence before promotion
- PIT-clean feature/target lineage.
- Independent validation/OOS evidence.
- Calibration evidence when probabilities are used.
- Uncertainty behavior and ablation evidence.
- Model artifact integrity and compatibility.
- Scope-of-validity evidence.

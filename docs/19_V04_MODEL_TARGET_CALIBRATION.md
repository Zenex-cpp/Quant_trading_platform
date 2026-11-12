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
Calibration is diagnostics-first: Brier score, ten-bin expected calibration error, per-bin reliability values, and drift against a distinct reference window. Each current and reference window needs a distinct evidence ID and at least 30 labeled outcomes by default. The signed model manifest's `calibration_state` is metadata only; live assessment requires a separately computed `CalibrationReport`, otherwise state is `UNKNOWN`. Its fingerprint binds source IDs, sample sizes, metrics, drift and thresholds through the risk decision. Missing report/evidence or insufficient samples returns `UNKNOWN`. Thresholds are registered before evaluation; generic defaults do not establish market-specific calibration. A report fingerprint is not a signature and does not authenticate its producer or dataset.

## Uncertainty
The uncertainty registry records source, method, definition, bounds, threshold, action and monitoring for signed model-declared uncertainty, Bernoulli entropy and ensemble dispersion. Entropy and ensemble dispersion remain experimental. Live risk evaluation accepts a source-bound assessment derived from a signed prediction and rejects scalar-only uncertainty. `conservative_risk_factor()` enforces a monotonic mapping where more uncertainty cannot increase risk; calibration states `UNKNOWN` and `POOR` cap the risk factor at 0.25, while `ACCEPTABLE` caps it at 0.50.

## Required evidence before promotion
- PIT-clean feature/target lineage.
- Independent validation/OOS evidence.
- Calibration evidence when probabilities are used.
- Uncertainty behavior and ablation evidence.
- Model artifact integrity and compatibility.
- Scope-of-validity evidence.

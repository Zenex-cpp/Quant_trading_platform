# V5.0 Model Card and Strategy Card Templates

These are descriptive, versioned artifacts for research and review. A completed card does not approve a model or strategy, validate its claims, authorize risk, or enable deployment.

## Model Card

The machine-readable template is src/trading_platform/research/model_card.py. Every field is required:

| Field | Required content |
|---|---|
| model_id, model_version | Stable identity and immutable version |
| intended_use, validity_scope | Permitted use and evidence-backed scope |
| training_data | Dataset identity, version, source and temporal coverage |
| features, target | Versioned feature and target definitions |
| regimes, prohibited_regimes | Supported and excluded conditions |
| limitations, failure_modes | Known limits and expected failure behavior |
| dependencies | Code, runtime, data and artifact dependencies |
| capital_range, venues, timeframes | Evaluated operating scope |
| execution_assumptions | Fill, latency, fees, slippage and capacity assumptions |
| approval_scope | Requested human approval scope; not an approval itself |

## Strategy Card

The machine-readable template is src/trading_platform/research/strategy_card.py. Required string fields must be non-empty; list fields are immutable tuples and may be empty only where the strategy has no entries for that category. The canonical JSON representation has a stable SHA-256 fingerprint.

| Field | Required content |
|---|---|
| strategy_id, strategy_version | Stable identity and immutable version |
| hypothesis | Falsifiable mechanism the strategy is designed to test |
| intended_use, validity_scope | Permitted use and evidence-backed scope |
| instruments, timeframes, regimes, prohibited_regimes | Declared operating domain |
| entry_logic, exit_logic | Decision rules at a reviewable level |
| signal_dependencies, data_requirements | Upstream signals and PIT/data requirements |
| portfolio_constraints, risk_controls | Allocation bounds and hard risk limits |
| execution_assumptions, cost_assumptions | Venue-independent assumptions to validate per adapter |
| capacity_limits, turnover_limits | Bounds beyond which the strategy is invalid |
| monitoring_metrics | Metrics and conditions that trigger review or disablement |
| known_limitations, failure_modes | Known weaknesses and fail-safe response |
| dependencies | Versioned models, features, targets, code and configuration |
| owner, approval_scope | Accountable owner and requested approval scope |

The card fingerprint covers every field. A changed field requires a new fingerprint and must flow through the repository compatibility, evidence invalidation, gate and promotion controls.

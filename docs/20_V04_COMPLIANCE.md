# V0.4 Compliance Delta

| Requirement | Status | Evidence |
|---|---|---|
| Target contract versioned | TESTED | `tests/test_v04_model.py` |
| Target available_at after horizon | TESTED | `tests/test_v04_model.py` |
| Model input/output schema contract | IMPLEMENTED/TESTED | model contract tests |
| Artifact integrity before load | TESTED | model contract tests |
| Calibration Brier/ECE, reliability, drift and evidence status; manifest state cannot substitute for a report | TESTED | calibration tests; `tests/test_v348_m21_uncertainty_risk.py`; `v04_calibration_registry.csv` |
| Source-bound uncertainty measurement, bounds, threshold, action and monitoring | TESTED | `v348_uncertainty_risk_registry.csv`; `tests/test_v348_m21_uncertainty_risk.py` |
| Higher uncertainty cannot increase risk at runtime, capability, durable decision and final dispatch | TESTED | `tests/test_v348_m21_uncertainty_risk.py`; `tests/v318/test_durable_decision.py` |
| RL experimental only | DOCUMENTED | model scope |
| Full model promotion | BLOCKED | V0.4 has no promotion engine |
| Final holdout isolation | IMPLEMENTED in V0.3 | V0.3 contract |
| Real dataset audit | BLOCKED | DATASET-01 not present |

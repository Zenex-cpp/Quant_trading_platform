# V0.4 Compliance Delta

| Requirement | Status | Evidence |
|---|---|---|
| Target contract versioned | TESTED | `tests/test_v04_model.py` |
| Target available_at after horizon | TESTED | `tests/test_v04_model.py` |
| Model input/output schema contract | IMPLEMENTED/TESTED | model contract tests |
| Artifact integrity before load | TESTED | model contract tests |
| Calibration Brier/ECE | TESTED | calibration tests |
| Calibration state | TESTED | calibration tests |
| Uncertainty measure | TESTED | uncertainty tests |
| Higher uncertainty cannot increase risk | TESTED | uncertainty monotonicity test |
| RL experimental only | DOCUMENTED | model scope |
| Full model promotion | BLOCKED | V0.4 has no promotion engine |
| Final holdout isolation | IMPLEMENTED in V0.3 | V0.3 contract |
| Real dataset audit | BLOCKED | DATASET-01 not present |

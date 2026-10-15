"""V0.5 robustness and adversarial evaluation primitives."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class RobustnessResult:
    scenario: str
    baseline_metric: float
    stressed_metric: float
    degradation: float
    threshold: float
    passed: bool
    methodology_version: str


def evaluate_degradation(baseline_metric: float, stressed_metric: float, max_degradation: float, scenario: str) -> RobustnessResult:
    if max_degradation < 0: raise ValueError("INVALID_ROBUSTNESS_THRESHOLD")
    degradation = baseline_metric - stressed_metric
    return RobustnessResult(scenario, float(baseline_metric), float(stressed_metric), float(degradation), float(max_degradation), degradation <= max_degradation, "ROBUSTNESS_V1")


def parameter_sensitivity(values: list[float], min_retention_ratio: float = 0.8) -> float:
    """Fraction of variants retaining a non-negative chosen metric direction."""
    if not values: raise ValueError("EMPTY_SENSITIVITY_SET")
    if not 0 < min_retention_ratio <= 1: raise ValueError("INVALID_RETENTION_RATIO")
    return float(np.mean(np.asarray(values) >= 0.0))

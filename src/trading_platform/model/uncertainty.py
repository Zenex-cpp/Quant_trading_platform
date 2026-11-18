"""Uncertainty measures with monotonic risk semantics."""
from __future__ import annotations
import math
from typing import Sequence


def bernoulli_entropy(probability: float) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("INVALID_PROBABILITY")
    if probability in (0.0, 1.0): return 0.0
    return -(probability * math.log(probability) + (1 - probability) * math.log(1 - probability)) / math.log(2)


def ensemble_dispersion(predictions: Sequence[float]) -> float:
    if len(predictions) < 2:
        raise ValueError("UNCERTAINTY_SAMPLE_TOO_SMALL")
    if any(not math.isfinite(p) or not 0.0 <= p <= 1.0 for p in predictions):
        raise ValueError("INVALID_ENSEMBLE_PROBABILITY")
    mean = sum(predictions) / len(predictions)
    return sum((p - mean) ** 2 for p in predictions) / len(predictions)


def conservative_risk_factor(uncertainty: float, max_uncertainty: float = 1.0,
                             floor: float = 0.0) -> float:
    if uncertainty < 0 or max_uncertainty <= 0 or not 0 <= floor <= 1:
        raise ValueError("INVALID_UNCERTAINTY_CONFIGURATION")
    normalized = min(1.0, uncertainty / max_uncertainty)
    return max(floor, 1.0 - normalized)

"""Calibration diagnostics and conservative probability calibration."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Sequence

@dataclass(frozen=True)
class CalibrationReport:
    method: str
    brier: float
    expected_calibration_error: float
    sample_size: int
    state: str


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("CALIBRATION_INPUT_INVALID")
    return sum((float(p) - int(y)) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities)


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> float:
    if len(probabilities) != len(outcomes) or not probabilities or bins < 2:
        raise ValueError("CALIBRATION_INPUT_INVALID")
    total = len(probabilities); ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i,p in enumerate(probabilities) if (lo <= p < hi) or (b == bins-1 and p == hi)]
        if not idx: continue
        conf = sum(probabilities[i] for i in idx) / len(idx)
        acc = sum(outcomes[i] for i in idx) / len(idx)
        ece += (len(idx) / total) * abs(conf - acc)
    return ece


def calibration_report(probabilities: Sequence[float], outcomes: Sequence[int], *, acceptable_brier: float = 0.25,
                       acceptable_ece: float = 0.10) -> CalibrationReport:
    b = brier_score(probabilities, outcomes); e = expected_calibration_error(probabilities, outcomes)
    state = "CALIBRATED" if b <= acceptable_brier and e <= acceptable_ece else "POOR"
    return CalibrationReport("EMPIRICAL_DIAGNOSTIC", b, e, len(probabilities), state)

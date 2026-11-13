"""Calibration diagnostics with explicit reference-window drift and evidence state."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import json
from typing import Sequence


@dataclass(frozen=True)
class ReliabilityBin:
    lower_bound: float
    upper_bound: float
    mean_probability: float
    observed_frequency: float
    sample_count: int


@dataclass(frozen=True)
class CalibrationReport:
    method: str
    source_id: str | None
    brier: float
    expected_calibration_error: float
    reliability: tuple[ReliabilityBin, ...]
    calibration_drift: float | None
    reference_brier: float | None
    reference_expected_calibration_error: float | None
    reference_source_id: str | None
    sample_size: int
    reference_sample_size: int
    state: str
    minimum_samples: int
    calibrated_brier_threshold: float
    calibrated_ece_threshold: float
    acceptable_brier_threshold: float
    acceptable_ece_threshold: float
    calibrated_max_drift: float
    acceptable_max_drift: float

    def payload(self) -> dict[str, object]:
        return {
            "method": self.method,
            "source_id": self.source_id,
            "brier": self.brier,
            "expected_calibration_error": self.expected_calibration_error,
            "reliability": [
                {
                    "lower_bound": item.lower_bound,
                    "upper_bound": item.upper_bound,
                    "mean_probability": item.mean_probability,
                    "observed_frequency": item.observed_frequency,
                    "sample_count": item.sample_count,
                }
                for item in self.reliability
            ],
            "calibration_drift": self.calibration_drift,
            "reference_brier": self.reference_brier,
            "reference_expected_calibration_error": self.reference_expected_calibration_error,
            "reference_source_id": self.reference_source_id,
            "sample_size": self.sample_size,
            "reference_sample_size": self.reference_sample_size,
            "state": self.state,
            "minimum_samples": self.minimum_samples,
            "calibrated_brier_threshold": self.calibrated_brier_threshold,
            "calibrated_ece_threshold": self.calibrated_ece_threshold,
            "acceptable_brier_threshold": self.acceptable_brier_threshold,
            "acceptable_ece_threshold": self.acceptable_ece_threshold,
            "calibrated_max_drift": self.calibrated_max_drift,
            "acceptable_max_drift": self.acceptable_max_drift,
        }

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def is_valid(self) -> bool:
        try:
            numeric = (
                self.brier,
                self.expected_calibration_error,
                self.calibrated_brier_threshold,
                self.calibrated_ece_threshold,
                self.acceptable_brier_threshold,
                self.acceptable_ece_threshold,
                self.calibrated_max_drift,
                self.acceptable_max_drift,
            )
            if (
                self.method != "EMPIRICAL_DIAGNOSTIC"
                or self.state not in {"CALIBRATED", "ACCEPTABLE", "POOR", "UNKNOWN"}
                or not isinstance(self.minimum_samples, int) or isinstance(self.minimum_samples, bool)
                or self.minimum_samples < 2
                or not isinstance(self.sample_size, int) or isinstance(self.sample_size, bool)
                or self.sample_size < 1
                or not isinstance(self.reference_sample_size, int) or isinstance(self.reference_sample_size, bool)
                or self.reference_sample_size < 0
                or any(not math.isfinite(value) or not 0 <= value <= 1 for value in numeric)
                or self.calibrated_brier_threshold > self.acceptable_brier_threshold
                or self.calibrated_ece_threshold > self.acceptable_ece_threshold
                or self.calibrated_max_drift > self.acceptable_max_drift
                or sum(item.sample_count for item in self.reliability) != self.sample_size
                or any(
                    not isinstance(item.sample_count, int) or isinstance(item.sample_count, bool)
                    or item.sample_count < 1
                    or not math.isfinite(item.lower_bound) or not math.isfinite(item.upper_bound)
                    or not math.isfinite(item.mean_probability) or not math.isfinite(item.observed_frequency)
                    or not 0 <= item.lower_bound < item.upper_bound <= 1
                    or not 0 <= item.mean_probability <= 1
                    or not 0 <= item.observed_frequency <= 1
                    for item in self.reliability
                )
                or any(
                    left.upper_bound > right.lower_bound
                    for left, right in zip(self.reliability, self.reliability[1:])
                )
            ):
                return False
            if self.state == "UNKNOWN":
                return self.calibration_drift is None and self.reference_brier is None and self.reference_expected_calibration_error is None
            if (
                not self.source_id or not self.source_id.strip()
                or not self.reference_source_id or not self.reference_source_id.strip()
                or self.source_id == self.reference_source_id
                or self.sample_size < self.minimum_samples
                or self.reference_sample_size < self.minimum_samples
                or self.reference_brier is None
                or self.reference_expected_calibration_error is None
                or self.calibration_drift is None
                or not math.isfinite(self.reference_brier)
                or not math.isfinite(self.reference_expected_calibration_error)
                or not math.isfinite(self.calibration_drift)
                or not 0 <= self.reference_brier <= 1
                or not 0 <= self.reference_expected_calibration_error <= 1
                or self.calibration_drift != max(
                    abs(self.brier - self.reference_brier),
                    abs(self.expected_calibration_error - self.reference_expected_calibration_error),
                )
            ):
                return False
            if (
                self.brier <= self.calibrated_brier_threshold
                and self.expected_calibration_error <= self.calibrated_ece_threshold
                and self.calibration_drift <= self.calibrated_max_drift
            ):
                return self.state == "CALIBRATED"
            if (
                self.brier <= self.acceptable_brier_threshold
                and self.expected_calibration_error <= self.acceptable_ece_threshold
                and self.calibration_drift <= self.acceptable_max_drift
            ):
                return self.state == "ACCEPTABLE"
            return self.state == "POOR"
        except (TypeError, ValueError, OverflowError):
            return False


def _validated_samples(probabilities: Sequence[float], outcomes: Sequence[int]) -> tuple[list[float], list[int]]:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("CALIBRATION_INPUT_INVALID")
    checked_probabilities: list[float] = []
    checked_outcomes: list[int] = []
    for probability, outcome in zip(probabilities, outcomes):
        if isinstance(probability, bool):
            raise ValueError("CALIBRATION_INPUT_INVALID")
        try:
            p = float(probability)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("CALIBRATION_INPUT_INVALID") from exc
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError("CALIBRATION_INPUT_INVALID")
        if isinstance(outcome, bool):
            y = int(outcome)
        elif isinstance(outcome, int) and outcome in (0, 1):
            y = outcome
        else:
            raise ValueError("CALIBRATION_INPUT_INVALID")
        checked_probabilities.append(p)
        checked_outcomes.append(y)
    return checked_probabilities, checked_outcomes


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    checked_probabilities, checked_outcomes = _validated_samples(probabilities, outcomes)
    return sum((p - y) ** 2 for p, y in zip(checked_probabilities, checked_outcomes)) / len(checked_probabilities)


def _reliability_bins(probabilities: Sequence[float], outcomes: Sequence[int], bins: int) -> tuple[ReliabilityBin, ...]:
    if bins < 2:
        raise ValueError("CALIBRATION_INPUT_INVALID")
    result: list[ReliabilityBin] = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            i for i, probability in enumerate(probabilities)
            if lower <= probability < upper or (index == bins - 1 and probability == upper)
        ]
        if not members:
            continue
        result.append(ReliabilityBin(
            lower_bound=lower,
            upper_bound=upper,
            mean_probability=sum(probabilities[i] for i in members) / len(members),
            observed_frequency=sum(outcomes[i] for i in members) / len(members),
            sample_count=len(members),
        ))
    return tuple(result)


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> float:
    checked_probabilities, checked_outcomes = _validated_samples(probabilities, outcomes)
    reliability = _reliability_bins(checked_probabilities, checked_outcomes, bins)
    total = len(checked_probabilities)
    return sum(
        item.sample_count / total * abs(item.mean_probability - item.observed_frequency)
        for item in reliability
    )


def calibration_report(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    source_id: str | None = None,
    reference_probabilities: Sequence[float] | None = None,
    reference_outcomes: Sequence[int] | None = None,
    reference_source_id: str | None = None,
    bins: int = 10,
    minimum_samples: int = 30,
    calibrated_brier: float = 0.10,
    calibrated_ece: float = 0.05,
    acceptable_brier: float = 0.25,
    acceptable_ece: float = 0.10,
    calibrated_max_drift: float = 0.05,
    acceptable_max_drift: float = 0.10,
) -> CalibrationReport:
    """Report score, reliability curve and drift against an earlier labeled window.

    A missing source, reference window, or minimum sample count yields UNKNOWN.
    Thresholds are explicit inputs and do not claim market-specific calibration.
    """
    current_p, current_y = _validated_samples(probabilities, outcomes)
    if bins < 2 or minimum_samples < 2:
        raise ValueError("CALIBRATION_CONFIGURATION_INVALID")
    limits = (
        calibrated_brier, calibrated_ece, acceptable_brier, acceptable_ece,
        calibrated_max_drift, acceptable_max_drift,
    )
    if any(not math.isfinite(float(value)) or not 0 <= float(value) <= 1 for value in limits):
        raise ValueError("CALIBRATION_CONFIGURATION_INVALID")
    if calibrated_brier > acceptable_brier or calibrated_ece > acceptable_ece:
        raise ValueError("CALIBRATION_CONFIGURATION_INVALID")
    if calibrated_max_drift > acceptable_max_drift:
        raise ValueError("CALIBRATION_CONFIGURATION_INVALID")

    current_brier = sum((p - y) ** 2 for p, y in zip(current_p, current_y)) / len(current_p)
    reliability = _reliability_bins(current_p, current_y, bins)
    current_ece = sum(
        item.sample_count / len(current_p) * abs(item.mean_probability - item.observed_frequency)
        for item in reliability
    )

    valid_reference = reference_probabilities is not None and reference_outcomes is not None
    reference_p: list[float] = []
    reference_y: list[int] = []
    if valid_reference:
        reference_p, reference_y = _validated_samples(reference_probabilities, reference_outcomes)
    enough_evidence = (
        bool(source_id and source_id.strip())
        and bool(reference_source_id and reference_source_id.strip())
        and source_id != reference_source_id
        and len(current_p) >= minimum_samples
        and valid_reference
        and len(reference_p) >= minimum_samples
    )
    drift: float | None = None
    reference_brier: float | None = None
    reference_ece: float | None = None
    state = "UNKNOWN"
    if enough_evidence:
        reference_brier = sum((p - y) ** 2 for p, y in zip(reference_p, reference_y)) / len(reference_p)
        reference_reliability = _reliability_bins(reference_p, reference_y, bins)
        reference_ece = sum(
            item.sample_count / len(reference_p) * abs(item.mean_probability - item.observed_frequency)
            for item in reference_reliability
        )
        drift = max(abs(current_brier - reference_brier), abs(current_ece - reference_ece))
        if current_brier <= calibrated_brier and current_ece <= calibrated_ece and drift <= calibrated_max_drift:
            state = "CALIBRATED"
        elif current_brier <= acceptable_brier and current_ece <= acceptable_ece and drift <= acceptable_max_drift:
            state = "ACCEPTABLE"
        else:
            state = "POOR"

    return CalibrationReport(
        method="EMPIRICAL_DIAGNOSTIC",
        source_id=source_id,
        brier=current_brier,
        expected_calibration_error=current_ece,
        reliability=reliability,
        calibration_drift=drift,
        reference_brier=reference_brier,
        reference_expected_calibration_error=reference_ece,
        reference_source_id=reference_source_id,
        sample_size=len(current_p),
        reference_sample_size=len(reference_p),
        state=state,
        minimum_samples=minimum_samples,
        calibrated_brier_threshold=float(calibrated_brier),
        calibrated_ece_threshold=float(calibrated_ece),
        acceptable_brier_threshold=float(acceptable_brier),
        acceptable_ece_threshold=float(acceptable_ece),
        calibrated_max_drift=float(calibrated_max_drift),
        acceptable_max_drift=float(acceptable_max_drift),
    )

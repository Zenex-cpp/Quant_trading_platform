from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping, Sequence
import hashlib, json, math

class DriftSeverity(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

@dataclass(frozen=True)
class DetectorConfig:
    detector_id: str
    version: str
    warning_threshold: Decimal
    critical_threshold: Decimal
    min_observations: int = 1
    max_missing_rate: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        if not self.detector_id or not self.version:
            raise ValueError("INVALID_DETECTOR_IDENTITY")
        if self.min_observations < 1:
            raise ValueError("INVALID_MIN_OBSERVATIONS")
        if not (self.warning_threshold >= 0 and self.critical_threshold > self.warning_threshold):
            raise ValueError("INVALID_DRIFT_THRESHOLDS")
        if not (Decimal("0") <= self.max_missing_rate <= Decimal("1")):
            raise ValueError("INVALID_MISSING_RATE_THRESHOLD")

@dataclass(frozen=True)
class DriftMetric:
    metric_id: str
    baseline: Decimal
    comparison: Decimal
    score: Decimal
    severity: DriftSeverity
    observations: int
    missing_rate: Decimal = Decimal("0")
    detector_id: str = ""
    detector_version: str = ""
    reason: str = ""

    @property
    def degraded(self) -> bool:
        return self.severity is not DriftSeverity.NONE


def _finite(x: Decimal) -> bool:
    return x.is_finite()


def _quantile_sorted(values: Sequence[Decimal], q: Decimal) -> Decimal:
    if not values:
        raise ValueError("EMPTY_SAMPLE")
    n = len(values)
    if n == 1:
        return values[0]
    pos = (Decimal(n - 1) * q)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - Decimal(lo)
    return values[lo] + (values[hi] - values[lo]) * frac


def _psi(baseline: Sequence[Decimal], comparison: Sequence[Decimal], bins: int = 10) -> Decimal:
    if not baseline or not comparison:
        raise ValueError("EMPTY_SAMPLE")
    b = sorted(baseline)
    edges = [_quantile_sorted(b, Decimal(i) / Decimal(bins)) for i in range(bins + 1)]
    # Strictly increasing edges are not guaranteed for tied data; use index-bucket fallback.
    def counts(vals: Sequence[Decimal]) -> list[int]:
        out = [0] * bins
        for x in vals:
            idx = 0
            while idx < bins - 1 and x > edges[idx + 1]:
                idx += 1
            out[idx] += 1
        return out
    bc, cc = counts(baseline), counts(comparison)
    bn, cn = Decimal(len(baseline)), Decimal(len(comparison))
    eps = Decimal("1e-12")
    total = Decimal("0")
    for bi, ci in zip(bc, cc):
        p = Decimal(bi) / bn
        q = Decimal(ci) / cn
        p = max(p, eps); q = max(q, eps)
        total += (q - p) * Decimal(str(math.log(float(q / p))))
    return total


class PopulationStabilityDetector:
    def __init__(self, config: DetectorConfig, bins: int = 10) -> None:
        if bins < 2:
            raise ValueError("INVALID_BIN_COUNT")
        self.config = config
        self.bins = bins

    def compare(self, metric_id: str, baseline: Sequence[Decimal], comparison: Sequence[Decimal], *, missing_rate: Decimal = Decimal("0")) -> DriftMetric:
        if any(not _finite(x) for x in (*baseline, *comparison)):
            raise ValueError("NON_FINITE_DRIFT_INPUT")
        observations = len(comparison)
        if observations < self.config.min_observations:
            return DriftMetric(metric_id, Decimal("0"), Decimal("0"), Decimal("0"), DriftSeverity.CRITICAL,
                               observations, missing_rate, self.config.detector_id, self.config.version, "INSUFFICIENT_OBSERVATIONS")
        if not (Decimal("0") <= missing_rate <= Decimal("1")) or not _finite(missing_rate):
            raise ValueError("INVALID_MISSING_RATE")
        score = _psi(list(baseline), list(comparison), self.bins)
        severity = DriftSeverity.CRITICAL if score >= self.config.critical_threshold else DriftSeverity.WARNING if score >= self.config.warning_threshold else DriftSeverity.NONE
        reason = "MISSINGNESS_CRITICAL" if missing_rate > self.config.max_missing_rate else ("PSI_CRITICAL" if severity is DriftSeverity.CRITICAL else "PSI_WARNING" if severity is DriftSeverity.WARNING else "STABLE")
        if missing_rate > self.config.max_missing_rate:
            severity = DriftSeverity.CRITICAL
        return DriftMetric(metric_id, sum(baseline, Decimal("0")) / Decimal(len(baseline)), sum(comparison, Decimal("0")) / Decimal(len(comparison)), score, severity,
                           observations, missing_rate, self.config.detector_id, self.config.version, reason)

@dataclass(frozen=True)
class MeanShiftDetector:
    config: DetectorConfig

    def compare(self, metric_id: str, baseline: Sequence[Decimal], comparison: Sequence[Decimal], *, missing_rate: Decimal = Decimal("0")) -> DriftMetric:
        if not baseline or not comparison:
            raise ValueError("EMPTY_SAMPLE")
        if any(not _finite(x) for x in (*baseline, *comparison)):
            raise ValueError("NON_FINITE_DRIFT_INPUT")
        b = sum(baseline, Decimal("0")) / Decimal(len(baseline))
        c = sum(comparison, Decimal("0")) / Decimal(len(comparison))
        scale = max(abs(b), Decimal("1e-12"))
        score = abs(c - b) / scale
        severity = DriftSeverity.CRITICAL if score >= self.config.critical_threshold else DriftSeverity.WARNING if score >= self.config.warning_threshold else DriftSeverity.NONE
        if missing_rate > self.config.max_missing_rate:
            severity = DriftSeverity.CRITICAL
            reason = "MISSINGNESS_CRITICAL"
        else:
            reason = "MEAN_SHIFT_CRITICAL" if severity is DriftSeverity.CRITICAL else "MEAN_SHIFT_WARNING" if severity is DriftSeverity.WARNING else "STABLE"
        return DriftMetric(metric_id, b, c, score, severity, len(comparison), missing_rate, self.config.detector_id, self.config.version, reason)

@dataclass(frozen=True)
class DriftReport:
    report_id: str
    created_at_ns: int
    metrics: tuple[DriftMetric, ...]
    detector_fingerprint: str

    @property
    def highest_severity(self) -> DriftSeverity:
        if any(m.severity is DriftSeverity.CRITICAL for m in self.metrics): return DriftSeverity.CRITICAL
        if any(m.severity is DriftSeverity.WARNING for m in self.metrics): return DriftSeverity.WARNING
        return DriftSeverity.NONE

    @property
    def trading_allowed(self) -> bool:
        return self.highest_severity is not DriftSeverity.CRITICAL

    def canonical_payload(self) -> dict:
        return {"report_id": self.report_id, "created_at_ns": self.created_at_ns,
                "metrics": [m.__dict__ | {"severity": m.severity.value} for m in self.metrics],
                "detector_fingerprint": self.detector_fingerprint}

    @property
    def state_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical_payload(), sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def detector_fingerprint(detectors: Iterable[DetectorConfig]) -> str:
    payload = [d.__dict__ for d in sorted(detectors, key=lambda x: (x.detector_id, x.version))]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

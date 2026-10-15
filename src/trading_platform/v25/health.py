from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"

@dataclass(frozen=True)
class EvidenceFreshness:
    evidence_id: str
    captured_at_ns: int
    ttl_ns: int
    verified: bool = True

    def valid_at(self, now_ns: int) -> bool:
        if not self.verified or self.ttl_ns <= 0 or now_ns < self.captured_at_ns:
            return False
        return now_ns - self.captured_at_ns <= self.ttl_ns

@dataclass(frozen=True)
class HealthAssessment:
    state: HealthState
    evidence_fresh: bool
    drift_critical: bool
    quality_ok: bool
    reason: str
    assessment_id: str

    @property
    def trading_allowed(self) -> bool:
        return self.state is HealthState.HEALTHY and self.evidence_fresh and self.quality_ok and not self.drift_critical


def assess_health(*, assessment_id: str, now_ns: int, evidence: EvidenceFreshness | None,
                  drift_critical: bool, quality_ok: bool = True, stream_healthy: bool = True) -> HealthAssessment:
    if evidence is None:
        return HealthAssessment(HealthState.UNKNOWN, False, drift_critical, quality_ok, "EVIDENCE_MISSING", assessment_id)
    fresh = evidence.valid_at(now_ns)
    if not stream_healthy:
        return HealthAssessment(HealthState.BLOCKED, fresh, drift_critical, quality_ok, "STREAM_UNHEALTHY", assessment_id)
    if drift_critical:
        return HealthAssessment(HealthState.BLOCKED, fresh, True, quality_ok, "DRIFT_CRITICAL", assessment_id)
    if not fresh:
        return HealthAssessment(HealthState.BLOCKED, False, False, quality_ok, "EVIDENCE_EXPIRED", assessment_id)
    if not quality_ok:
        return HealthAssessment(HealthState.DEGRADED, True, False, False, "DATA_QUALITY_DEGRADED", assessment_id)
    return HealthAssessment(HealthState.HEALTHY, True, False, True, "HEALTHY", assessment_id)

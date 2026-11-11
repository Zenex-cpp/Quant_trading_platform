from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
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
        if (
            not isinstance(self.evidence_id, str)
            or not self.evidence_id.strip()
            or self.verified is not True
            or not isinstance(self.captured_at_ns, int)
            or isinstance(self.captured_at_ns, bool)
            or not isinstance(self.ttl_ns, int)
            or isinstance(self.ttl_ns, bool)
            or not isinstance(now_ns, int)
            or isinstance(now_ns, bool)
            or self.captured_at_ns < 0
            or self.ttl_ns <= 0
            or now_ns < self.captured_at_ns
        ):
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
    source_evidence: EvidenceFreshness | None = None
    assessed_at_ns: int | None = None

    @property
    def source_fingerprint(self) -> str | None:
        evidence = self.source_evidence
        if evidence is None or self.assessed_at_ns is None:
            return None
        payload = {
            "assessment_id": self.assessment_id,
            "assessed_at_ns": self.assessed_at_ns,
            "state": getattr(self.state, "value", str(self.state)),
            "evidence_fresh": self.evidence_fresh,
            "drift_critical": self.drift_critical,
            "quality_ok": self.quality_ok,
            "evidence_id": evidence.evidence_id,
            "captured_at_ns": evidence.captured_at_ns,
            "ttl_ns": evidence.ttl_ns,
            "verified": evidence.verified,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    def source_fresh_at(self, now_ns: int) -> bool:
        evidence = self.source_evidence
        return (
            evidence is not None
            and self.assessed_at_ns is not None
            and isinstance(self.assessed_at_ns, int)
            and not isinstance(self.assessed_at_ns, bool)
            and evidence.valid_at(self.assessed_at_ns)
            and evidence.valid_at(now_ns)
        )

    @property
    def trading_allowed(self) -> bool:
        return self.state is HealthState.HEALTHY and self.evidence_fresh and self.quality_ok and not self.drift_critical


def assess_health(*, assessment_id: str, now_ns: int, evidence: EvidenceFreshness | None,
                  drift_critical: bool, quality_ok: bool = True, stream_healthy: bool = True) -> HealthAssessment:
    def result(state: HealthState, fresh: bool, reason: str) -> HealthAssessment:
        return HealthAssessment(
            state, fresh, drift_critical, quality_ok, reason, assessment_id,
            source_evidence=evidence, assessed_at_ns=now_ns,
        )

    if evidence is None:
        return result(HealthState.UNKNOWN, False, "EVIDENCE_MISSING")
    fresh = evidence.valid_at(now_ns)
    if not stream_healthy:
        return result(HealthState.BLOCKED, fresh, "STREAM_UNHEALTHY")
    if drift_critical:
        return result(HealthState.BLOCKED, fresh, "DRIFT_CRITICAL")
    if not fresh:
        return result(HealthState.BLOCKED, False, "EVIDENCE_EXPIRED")
    if not quality_ok:
        return result(HealthState.DEGRADED, True, "DATA_QUALITY_DEGRADED")
    return result(HealthState.HEALTHY, True, "HEALTHY")

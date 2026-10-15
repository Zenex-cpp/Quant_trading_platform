from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .health import HealthAssessment
from .drift import DriftReport, DriftSeverity

class FreezeState(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"

@dataclass(frozen=True)
class FreezeDecision:
    state: FreezeState
    reason: str
    report_hash: str
    assessment_id: str
    risk_cap: str

class FreezeController:
    def evaluate(self, *, report: DriftReport, health: HealthAssessment, current_risk_cap: str = "0") -> FreezeDecision:
        if report.highest_severity is DriftSeverity.CRITICAL:
            return FreezeDecision(FreezeState.FROZEN, "DRIFT_CRITICAL", report.state_hash, health.assessment_id, "0")
        if not health.trading_allowed:
            return FreezeDecision(FreezeState.FROZEN, health.reason, report.state_hash, health.assessment_id, "0")
        return FreezeDecision(FreezeState.ACTIVE, "NO_FREEZE_TRIGGER", report.state_hash, health.assessment_id, current_risk_cap)

    def require_active(self, decision: FreezeDecision) -> None:
        if decision.state is not FreezeState.ACTIVE:
            raise PermissionError(f"TRADING_FROZEN:{decision.reason}")

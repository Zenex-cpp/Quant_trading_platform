from __future__ import annotations
from dataclasses import dataclass
from .scenarios import offline_plan, ScenarioStatus

@dataclass(frozen=True)
class VerificationSummary:
    total: int
    passed: int
    failed: int
    not_verified: int
    production_ready: bool

def offline_verification_summary()->VerificationSummary:
    plan=offline_plan(); vals=list(plan.values())
    return VerificationSummary(len(vals), vals.count(ScenarioStatus.PASS), vals.count(ScenarioStatus.FAIL), vals.count(ScenarioStatus.NOT_VERIFIED), False)

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json

from trading_platform.v25.health import HealthAssessment, HealthState
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState

class GovernanceStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DEGRADED = "DEGRADED"
    DEMOTED = "DEMOTED"
    QUARANTINED = "QUARANTINED"
    BLOCKED = "BLOCKED"

@dataclass(frozen=True)
class EvidenceValidity:
    evidence_id: str
    valid: bool
    reason: str
    checked_at_ns: int

@dataclass(frozen=True)
class GovernedModel:
    model_id: str
    version: str
    role: ModelRole
    mode: OperationalMode
    deployment: DeploymentState
    health: HealthState
    governance: GovernanceStatus
    evidence_valid: bool
    approval_valid: bool
    effective_risk_budget: Decimal
    invalidation_reason: str | None = None
    @property
    def trading_allowed(self) -> bool:
        return self.governance is GovernanceStatus.ELIGIBLE and self.role is ModelRole.CHAMPION and self.mode is OperationalMode.LIVE and self.deployment is DeploymentState.ACTIVE and self.health is HealthState.HEALTHY and self.evidence_valid and self.approval_valid and self.effective_risk_budget > 0

@dataclass(frozen=True)
class GovernanceDecision:
    decision_id: str
    model_id: str
    status: GovernanceStatus
    role: ModelRole
    mode: OperationalMode
    effective_risk_budget: Decimal
    reason: str
    evidence_valid: bool
    @property
    def state_hash(self) -> str:
        payload = {"decision_id":self.decision_id,"model_id":self.model_id,"status":self.status.value,"role":self.role.value,"mode":self.mode.value,"effective_risk_budget":str(self.effective_risk_budget),"reason":self.reason,"evidence_valid":self.evidence_valid}
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def evaluate_model(*, model: GovernedModel, health: HealthAssessment, evidence: EvidenceValidity, approved_risk_budget: Decimal) -> GovernanceDecision:
    if approved_risk_budget < 0: raise ValueError("NEGATIVE_RISK_BUDGET")
    if not evidence.evidence_id: raise ValueError("EVIDENCE_ID_REQUIRED")
    status, effective, reason = GovernanceStatus.ELIGIBLE, approved_risk_budget, "HEALTHY"
    if not evidence.valid:
        status, effective, reason = GovernanceStatus.QUARANTINED, Decimal("0"), f"EVIDENCE_INVALID:{evidence.reason}"
    elif health.state in {HealthState.UNKNOWN, HealthState.BLOCKED} or health.drift_critical:
        status, effective, reason = GovernanceStatus.QUARANTINED, Decimal("0"), health.reason
    elif health.state is HealthState.DEGRADED:
        status, effective, reason = GovernanceStatus.DEMOTED, (approved_risk_budget * Decimal("0.50")).quantize(Decimal("0.00000001")), health.reason
    elif not health.trading_allowed:
        status, effective, reason = GovernanceStatus.BLOCKED, Decimal("0"), "HEALTH_NOT_TRADABLE"
    if model.role is ModelRole.CHALLENGER and model.mode is OperationalMode.LIVE:
        status, effective, reason = GovernanceStatus.BLOCKED, Decimal("0"), "CHALLENGER_LIVE_FORBIDDEN"
    if model.mode is OperationalMode.SHADOW:
        effective = Decimal("0")
        reason = "SHADOW_RISK_ZERO" if status is GovernanceStatus.ELIGIBLE else reason
    return GovernanceDecision(sha256(f"{model.model_id}|{health.assessment_id}|{evidence.evidence_id}|{evidence.valid}|{health.state.value}".encode()).hexdigest()[:24], model.model_id, status, model.role, model.mode, effective, reason, evidence.valid)

def invalidate_promotion(*, model: GovernedModel, reason: str) -> GovernedModel:
    if not reason: raise ValueError("INVALIDATION_REASON_REQUIRED")
    return GovernedModel(model.model_id, model.version, model.role, model.mode, model.deployment, HealthState.BLOCKED, GovernanceStatus.QUARANTINED, False, False, Decimal("0"), reason)

@dataclass(frozen=True)
class ChampionChallengerRegistry:
    models: tuple[GovernedModel, ...]
    def __post_init__(self):
        active = [m for m in self.models if m.role is ModelRole.CHAMPION and m.governance not in {GovernanceStatus.QUARANTINED, GovernanceStatus.BLOCKED}]
        if len(active) > 1: raise ValueError("MULTIPLE_ACTIVE_CHAMPIONS")
    def champion(self):
        return next((m for m in self.models if m.role is ModelRole.CHAMPION), None)
    def active_challengers(self):
        return tuple(m for m in self.models if m.role is ModelRole.CHALLENGER and m.governance not in {GovernanceStatus.QUARANTINED, GovernanceStatus.BLOCKED})
    def promote(self, challenger_id: str, *, validated: bool, gate_authorization=None, evidence_snapshot_authorization=None, promotion_bundle_authorization_id=None, dependency_authority=None, now=None):
        if not validated: raise ValueError("PROMOTION_VALIDATION_REQUIRED")
        if gate_authorization is None or evidence_snapshot_authorization is None or promotion_bundle_authorization_id is None or dependency_authority is None or now is None:
            raise ValueError("CHAMPION_GATE_EVIDENCE_AND_BUNDLE_AUTHORITY_REQUIRED")
        from trading_platform.v334.champion_authority import ChampionGateAuthorityError
        c = next((m for m in self.models if m.model_id == challenger_id), None)
        if c is None or c.role is not ModelRole.CHALLENGER: raise ValueError("CHALLENGER_REQUIRED")
        if c.governance is not GovernanceStatus.ELIGIBLE or not c.evidence_valid or c.health is not HealthState.HEALTHY: raise ValueError("CHALLENGER_NOT_PROMOTABLE")
        try:
            from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger
            ChampionGateAuthorityLedger(dependency_authority.store).assert_valid(
                gate_authorization.authorization_id, now=now, model_id=c.model_id, model_version=c.version,
                candidate_id=c.model_id, promotion_id=gate_authorization.promotion_id,
                dependency_authority=dependency_authority,
            )
        except Exception as exc:
            raise ValueError("CHAMPION_GATE_AUTHORITY_BLOCKED") from exc
        try:
            from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityError, PromotionBundleAuthorityLedger
            PromotionBundleAuthorityLedger(dependency_authority.store).assert_valid_binding(
                promotion_bundle_authorization_id,
                bundle_id=gate_authorization.promotion_id,
                model_version=c.version,
                now=now,
                dependency_authority=dependency_authority,
            )
        except Exception as exc:
            raise ValueError("PROMOTION_BUNDLE_AUTHORITY_BLOCKED") from exc
        try:
            from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError, EvidenceSnapshotAuthorityLedger
            EvidenceSnapshotAuthorityLedger(dependency_authority.store).assert_valid(
                evidence_snapshot_authorization.snapshot_id, now=now,
                promotion_id=gate_authorization.promotion_id, bundle_id=gate_authorization.promotion_id,
                model_version=c.version, required_gate_ids=gate_authorization.required_gate_ids,
                dependency_authority=dependency_authority,
            )
        except Exception as exc:
            raise ValueError("EVIDENCE_SNAPSHOT_AUTHORITY_BLOCKED") from exc
        out=[]
        for m in self.models:
            if m.model_id == challenger_id:
                out.append(GovernedModel(m.model_id,m.version,ModelRole.CHAMPION,OperationalMode.LIVE,DeploymentState.ACTIVE,m.health,GovernanceStatus.ELIGIBLE,m.evidence_valid,m.approval_valid,m.effective_risk_budget))
            elif m.role is ModelRole.CHAMPION:
                out.append(GovernedModel(m.model_id,m.version,ModelRole.CHALLENGER,OperationalMode.SHADOW,DeploymentState.ACTIVE,m.health,GovernanceStatus.ELIGIBLE,m.evidence_valid,m.approval_valid,Decimal("0")))
            else: out.append(m)
        return ChampionChallengerRegistry(tuple(out))
    def quarantine(self, model_id: str, *, reason: str):
        if not any(m.model_id == model_id for m in self.models): raise ValueError("MODEL_NOT_FOUND")
        return ChampionChallengerRegistry(tuple(invalidate_promotion(model=m, reason=reason) if m.model_id == model_id else m for m in self.models))

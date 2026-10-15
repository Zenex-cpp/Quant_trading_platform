from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from enum import Enum
from hashlib import sha256
import json

class ModelRole(str, Enum):
    NONE = "NONE"
    CHALLENGER = "CHALLENGER"
    CHAMPION = "CHAMPION"

class OperationalMode(str, Enum):
    RESEARCH="RESEARCH"
    BACKTEST="BACKTEST"
    SIMULATION="SIMULATION"
    SHADOW="SHADOW"
    CANARY="CANARY"
    LIVE="LIVE"
    CLOSING_ONLY="CLOSING_ONLY"

class DeploymentState(str, Enum):
    NOT_DEPLOYED="NOT_DEPLOYED"
    STAGED="STAGED"
    ACTIVE="ACTIVE"
    ROLLED_BACK="ROLLED_BACK"
    FAILED="FAILED"

@dataclass(frozen=True)
class Approval:
    approval_id: str
    approved_by: tuple[str,...]
    valid_from: datetime
    expires_at: datetime
    scope: dict[str,str]
    status: str = "APPROVED"
    def validate(self, now: datetime) -> None:
        if self.valid_from.tzinfo is None or self.expires_at.tzinfo is None or now.tzinfo is None:
            raise ValueError("APPROVAL_TIMEZONE_REQUIRED")
        if self.expires_at <= self.valid_from or now < self.valid_from:
            raise ValueError("APPROVAL_NOT_YET_VALID")
        if now >= self.expires_at or self.status != "APPROVED":
            raise ValueError("APPROVAL_EXPIRED_OR_INVALID")
        if not self.approved_by:
            raise ValueError("APPROVER_REQUIRED")

@dataclass(frozen=True)
class PromotionBundle:
    bundle_id: str
    strategy_version: str
    model_version: str
    feature_version: str
    target_version: str
    configuration_version: str
    execution_model_version: str
    code_version: str
    evidence_snapshot_id: str
    gate_results: tuple[str,...]
    artifact_hashes: tuple[str,...]
    approval_id: str
    scope: dict[str,str]
    rollback_target: str
    content_hash: str
    created_at: datetime
    def validate(self) -> None:
        required=(self.bundle_id,self.strategy_version,self.model_version,self.feature_version,self.target_version,self.configuration_version,self.execution_model_version,self.code_version,self.evidence_snapshot_id,self.approval_id,self.rollback_target,self.content_hash)
        if any(not x for x in required): raise ValueError("PROMOTION_BUNDLE_INCOMPLETE")
        if not self.gate_results or not self.artifact_hashes: raise ValueError("PROMOTION_BUNDLE_EVIDENCE_REQUIRED")
        if self.created_at.tzinfo is None: raise ValueError("BUNDLE_TIMEZONE_REQUIRED")

def bundle_hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str).encode()).hexdigest()

@dataclass(frozen=True)
class PromotionDecision:
    decision_id: str
    candidate_id: str
    bundle_id: str
    decision: str
    rationale: str
    actor: str
    decided_at: datetime
    approval_id: str | None

@dataclass(frozen=True)
class GateSummary:
    required_gate_ids: tuple[str,...]
    passed_gate_ids: tuple[str,...]
    invalidated_gate_ids: tuple[str,...]
    def all_required_passed(self, dependency_authority: "DependencyInvalidationLedger") -> bool:
        if dependency_authority is None:
            raise ValueError("DEPENDENCY_AUTHORITY_REQUIRED")
        dependency_authority.assert_clear(self.required_gate_ids)
        required=set(self.required_gate_ids)
        return required.issubset(self.passed_gate_ids) and not (required & set(self.invalidated_gate_ids))

@dataclass(frozen=True)
class ScopeCheck:
    valid: bool
    reason: str

def check_scope(bundle: PromotionBundle, requested: dict[str,str]) -> ScopeCheck:
    for key,value in requested.items():
        allowed=bundle.scope.get(key)
        if allowed not in (None, "*", value):
            return ScopeCheck(False, f"SCOPE_MISMATCH:{key}")
    return ScopeCheck(True,"SCOPE_VALID")

def promotion_allowed(*, bundle: PromotionBundle, gates: GateSummary, approval: Approval, evidence_valid: bool, compatibility_valid: bool, scope: ScopeCheck, artifacts_integrity: bool, now: datetime, dependency_authority: "DependencyInvalidationLedger", promotion_bundle_authorization_id: str | None = None) -> bool:
    try: bundle.validate(); approval.validate(now)
    except ValueError: return False
    if not promotion_bundle_authorization_id:
        return False
    try:
        from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityError, PromotionBundleAuthorityLedger
        PromotionBundleAuthorityLedger(dependency_authority.store).assert_valid(
            promotion_bundle_authorization_id,
            bundle=bundle,
            now=now,
            dependency_authority=dependency_authority,
        )
        dependencies = (
            bundle.bundle_id, bundle.evidence_snapshot_id,
            *bundle.gate_results, bundle.strategy_version, bundle.model_version,
            bundle.feature_version, bundle.target_version, bundle.configuration_version,
            bundle.execution_model_version, bundle.code_version,
        )
        dependency_authority.assert_clear(dependencies)
        gate_pass = gates.all_required_passed(dependency_authority)
        from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError, EvidenceSnapshotAuthorityLedger
        EvidenceSnapshotAuthorityLedger(dependency_authority.store).assert_valid(
            bundle.evidence_snapshot_id,
            now=now,
            promotion_id=bundle.bundle_id,
            bundle_id=bundle.bundle_id,
            model_version=bundle.model_version,
            required_gate_ids=bundle.gate_results,
            required_artifact_hashes=bundle.artifact_hashes,
            required_versions=(bundle.strategy_version, bundle.model_version, bundle.feature_version, bundle.target_version,
                               bundle.configuration_version, bundle.execution_model_version, bundle.code_version),
            approval_id=bundle.approval_id,
            requested_scope=bundle.scope,
            dependency_authority=dependency_authority,
        )
    except Exception as exc:
        from trading_platform.v329.dependency_authority import DependencyInvalidationError
        from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError
        from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityError
        if isinstance(exc, (DependencyInvalidationError, EvidenceSnapshotAuthorityError, PromotionBundleAuthorityError)):
            return False
        raise
    return all((gate_pass, evidence_valid, compatibility_valid, scope.valid, artifacts_integrity))

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.operations.readiness import OperationalReadiness, ReadinessStatus
from trading_platform.promotion.contracts import (
    Approval,
    GateSummary,
    PromotionBundle,
    ScopeCheck,
    promotion_allowed,
)
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState, assert_runtime_activation
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentState as LegacyDeploymentState
from trading_platform.v28.deployment_authority import activation_capability_context, _issue_activation_capability
from trading_platform.state.enums import OperationalMode
from trading_platform.v30.truth import CanonicalAction, OperationalTruth
from trading_platform.v31.authority import AuthorityDecision, AuthorityStatus, RuntimeAuthority
from trading_platform.v324.recovery_proof import RecoveryProofLedger, RecoveryProofRecord
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.v357.downstream_dependency import DependencyReference, DownstreamDependencyAuthorityLedger, DownstreamDependencyBlocked
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger, ChampionGateAuthorityError
from trading_platform.v340.reconciliation_authority import ReconciliationAuthorityLedger, ReconciliationAuthorityError
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityLedger, CompatibilityAuthorityError
from trading_platform.v342.artifact_integrity import ArtifactIntegrityAuthorityLedger, ArtifactIntegrityAuthorityError
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger, PromotionBundleAuthorityError
from trading_platform.v355.recovery_readiness import RecoveryReadinessLedger, RecoveryReadinessAuthorityError
from trading_platform.v359.human_review import HumanReviewAuthorityLedger, HumanReviewAuthorityError


class ActivationInvalid(RuntimeError):
    """Deployment activation evidence is absent, malformed or not authorized."""


class ActivationExpired(ActivationInvalid):
    """Deployment activation evidence is outside its validity window."""


class ActivationConflict(RuntimeError):
    """A deployment activation identity was reused with incompatible content."""


class DeploymentActivationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DeploymentActivationRecord:
    deployment_id: str
    bundle_id: str
    approval_id: str
    proof_id: str
    target_mode: OperationalMode
    valid_from: datetime
    expires_at: datetime
    state_fingerprint: str
    recovery_proof_fingerprint: str
    recovery_readiness_authorization_id: str
    recovery_readiness_fingerprint: str
    promotion_fingerprint: str
    truth_hash: str
    authority_decision_id: str
    authority_reason: str
    requested_risk: Decimal
    effective_risk: Decimal
    canary_exposure: Decimal
    operator: str
    reconciliation_authorization_id: str
    reconciliation_scope: str
    compatibility_authorization_id: str
    artifact_integrity_authorization_id: str
    promotion_bundle_authorization_id: str
    recorded_at_ms: int
    human_review_authorization_id: str | None = None

    @property
    def status(self) -> DeploymentActivationStatus:
        return DeploymentActivationStatus.AUTHORIZED

    @property
    def fingerprint(self) -> str:
        return DeploymentActivationLedger.fingerprint_from_payload(
            DeploymentActivationLedger.payload_from_record(self)
        )


class DeploymentActivationLedger:
    """Append-only authority for controlled deployment activation.

    V3.25 closes the boundary between readiness evidence and actual activation:
    a CANARY/LIVE activation authorization is durable, expires no later than its
    approval/recovery evidence, and is bound to the current state and Operational Truth.
    """

    RECORDED = "DEPLOYMENT_ACTIVATION_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"INVALID_ACTIVATION_{field}")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @classmethod
    def promotion_fingerprint(
        cls,
        *,
        bundle: PromotionBundle,
        approval: Approval,
        gates: GateSummary,
        scope: ScopeCheck,
        evidence_valid: bool,
        compatibility_valid: bool,
        artifacts_integrity: bool,
    ) -> str:
        payload = {
            "bundle": {
                "bundle_id": bundle.bundle_id,
                "strategy_version": bundle.strategy_version,
                "model_version": bundle.model_version,
                "feature_version": bundle.feature_version,
                "target_version": bundle.target_version,
                "configuration_version": bundle.configuration_version,
                "execution_model_version": bundle.execution_model_version,
                "code_version": bundle.code_version,
                "evidence_snapshot_id": bundle.evidence_snapshot_id,
                "gate_results": list(bundle.gate_results),
                "artifact_hashes": list(bundle.artifact_hashes),
                "approval_id": bundle.approval_id,
                "scope": dict(bundle.scope),
                "rollback_target": bundle.rollback_target,
                "content_hash": bundle.content_hash,
            },
            "approval": {
                "approval_id": approval.approval_id,
                "status": approval.status,
                "approved_by": list(approval.approved_by),
                "valid_from": cls._iso(approval.valid_from, "APPROVAL_VALID_FROM"),
                "expires_at": cls._iso(approval.expires_at, "APPROVAL_EXPIRES_AT"),
                "scope": dict(approval.scope),
            },
            "gates": {
                "required": list(gates.required_gate_ids),
                "passed": list(gates.passed_gate_ids),
                "invalidated": list(gates.invalidated_gate_ids),
            },
            "scope": {"valid": scope.valid, "reason": scope.reason},
            "evidence_valid": bool(evidence_valid),
            "compatibility_valid": bool(compatibility_valid),
            "artifacts_integrity": bool(artifacts_integrity),
        }
        return cls.fingerprint_from_payload(payload)

    @classmethod
    def payload_from_record(cls, record: DeploymentActivationRecord) -> dict[str, Any]:
        return {
            "deployment_id": record.deployment_id,
            "bundle_id": record.bundle_id,
            "approval_id": record.approval_id,
            "proof_id": record.proof_id,
            "target_mode": record.target_mode.value,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "state_fingerprint": record.state_fingerprint,
            "recovery_proof_fingerprint": record.recovery_proof_fingerprint,
            "recovery_readiness_authorization_id": record.recovery_readiness_authorization_id,
            "recovery_readiness_fingerprint": record.recovery_readiness_fingerprint,
            "promotion_fingerprint": record.promotion_fingerprint,
            "truth_hash": record.truth_hash,
            "authority_decision_id": record.authority_decision_id,
            "authority_reason": record.authority_reason,
            "requested_risk": str(record.requested_risk),
            "effective_risk": str(record.effective_risk),
            "canary_exposure": str(record.canary_exposure),
            "operator": record.operator,
            "reconciliation_authorization_id": record.reconciliation_authorization_id,
            "reconciliation_scope": record.reconciliation_scope,
            "compatibility_authorization_id": record.compatibility_authorization_id,
            "artifact_integrity_authorization_id": record.artifact_integrity_authorization_id,
            "promotion_bundle_authorization_id": record.promotion_bundle_authorization_id,
            "recorded_at_ms": record.recorded_at_ms,
            "human_review_authorization_id": record.human_review_authorization_id,
        }

    @classmethod
    def authorize(
        cls,
        *,
        deployment_id: str,
        bundle: PromotionBundle,
        approval: Approval,
        gates: GateSummary,
        scope: ScopeCheck,
        evidence_valid: bool,
        compatibility_valid: bool,
        artifacts_integrity: bool,
        readiness: OperationalReadiness,
        target_mode: OperationalMode,
        proof_ledger: RecoveryProofLedger,
        proof_id: str | None,
        current_state_fingerprint: str,
        truth: OperationalTruth,
        requested_risk: Decimal,
        canary_exposure: Decimal,
        runtime_state: RuntimeBundleState,
        rollout_policy: RolloutPolicy,
        operator: str,
        decision_id: str,
        now: datetime,
        recorded_at_ms: int,
        authority: RuntimeAuthority | None = None,
        store: EventStore | None = None,
        champion_gate_authorization_id: str | None = None,
        reconciliation_authorization_id: str | None = None,
        reconciliation_scope: str = "PRODUCTION",
        compatibility_authorization_id: str | None = None,
        artifact_integrity_authorization_id: str | None = None,
        promotion_bundle_authorization_id: str | None = None,
        human_review_authorization_id: str | None = None,
    ) -> tuple[DeploymentActivationRecord, bool]:
        store = store or proof_ledger.store
        ledger = cls(store)
        if target_mode not in {OperationalMode.CANARY, OperationalMode.LIVE}:
            raise ActivationInvalid("ACTIVATION_TARGET_MODE_NOT_CONTROLLED")
        if not deployment_id or not operator or not current_state_fingerprint or not decision_id:
            raise ActivationInvalid("ACTIVATION_IDENTIFIERS_REQUIRED")
        if requested_risk < 0 or canary_exposure < 0 or not requested_risk.is_finite() or not canary_exposure.is_finite():
            raise ActivationInvalid("INVALID_ACTIVATION_RISK")
        if recorded_at_ms < 0:
            raise ActivationInvalid("INVALID_ACTIVATION_TIMESTAMP")
        if not store.verify_chain():
            raise ActivationInvalid("ACTIVATION_EVENT_CHAIN_INVALID")
        if readiness.status() is not ReadinessStatus.READY_FOR_LIVE:
            raise ActivationInvalid("OPERATIONAL_READINESS_BLOCKED")
        if not proof_id:
            raise ActivationInvalid("RECOVERY_PROOF_REQUIRED")
        proof = proof_ledger.assert_valid(
            proof_id,
            now=now,
            current_state_fingerprint=current_state_fingerprint,
        )
        try:
            readiness_auth = RecoveryReadinessLedger(store).authorize(
                authorization_id=f"{deployment_id}:recovery-readiness",
                readiness=readiness,
                target_mode=target_mode,
                proof_ledger=proof_ledger,
                proof_id=proof.proof_id,
                now=now,
                current_state_fingerprint=current_state_fingerprint,
                recorded_at_ms=recorded_at_ms,
            )
        except RecoveryReadinessAuthorityError as exc:
            raise ActivationInvalid(f"RECOVERY_READINESS_BLOCKED:{exc}") from exc
        bundle.validate()
        dependency_ledger = DependencyInvalidationLedger(store)
        try:
            dependency_ledger.assert_clear((
                bundle.bundle_id,
                bundle.evidence_snapshot_id,
                *bundle.gate_results,
                bundle.strategy_version,
                bundle.model_version,
                bundle.feature_version,
                bundle.target_version,
                bundle.configuration_version,
                bundle.execution_model_version,
                bundle.code_version,
            ))
        except DependencyInvalidationBlocked as exc:
            raise ActivationInvalid("DEPENDENCY_INVALIDATION_BLOCKED") from exc
        if target_mode is OperationalMode.LIVE and not champion_gate_authorization_id:
            raise ActivationInvalid("LIVE_CHAMPION_GATE_AUTHORITY_REQUIRED")
        if target_mode is OperationalMode.LIVE:
            if not human_review_authorization_id:
                raise ActivationInvalid("LIVE_HUMAN_REVIEW_AUTHORITY_REQUIRED")
            try:
                HumanReviewAuthorityLedger(store).assert_valid(
                    human_review_authorization_id,
                    bundle=bundle,
                    approval=approval,
                    now=now,
                    dependency_authority=dependency_ledger,
                )
            except HumanReviewAuthorityError as exc:
                raise ActivationInvalid(f"LIVE_HUMAN_REVIEW_BLOCKED:{exc}") from exc
        if not compatibility_authorization_id:
            raise ActivationInvalid("COMPATIBILITY_AUTHORITY_REQUIRED")
        if not artifact_integrity_authorization_id:
            raise ActivationInvalid("ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED")
        if not promotion_bundle_authorization_id:
            raise ActivationInvalid("PROMOTION_BUNDLE_AUTHORITY_REQUIRED")
        if not reconciliation_authorization_id:
            raise ActivationInvalid("RECONCILIATION_AUTHORITY_REQUIRED")
        try:
            PromotionBundleAuthorityLedger(store).assert_valid(
                promotion_bundle_authorization_id,
                bundle=bundle,
                now=now,
                dependency_authority=dependency_ledger,
            )
        except PromotionBundleAuthorityError as exc:
            raise ActivationInvalid(f"PROMOTION_BUNDLE_AUTHORITY_BLOCKED:{exc}") from exc
        if not promotion_allowed(
            bundle=bundle,
            gates=gates,
            approval=approval,
            evidence_valid=evidence_valid,
            compatibility_valid=compatibility_valid,
            scope=scope,
            artifacts_integrity=artifacts_integrity,
            now=now,
            dependency_authority=dependency_ledger,
            promotion_bundle_authorization_id=promotion_bundle_authorization_id,
        ):
            raise ActivationInvalid("PROMOTION_AUTHORITY_BLOCKED")
        promo_fp = cls.promotion_fingerprint(
            bundle=bundle, approval=approval, gates=gates, scope=scope,
            evidence_valid=evidence_valid, compatibility_valid=compatibility_valid,
            artifacts_integrity=artifacts_integrity,
        )
        runtime_authority = authority or RuntimeAuthority()
        deployment_decision = runtime_authority.evaluate(
            truth=truth,
            action=CanonicalAction.DEPLOY,
            requested_risk=requested_risk,
            decision_id=decision_id,
            input_payload={
                "deployment_id": deployment_id,
                "bundle_id": bundle.bundle_id,
                "proof_id": proof.proof_id,
                "target_mode": target_mode.value,
                "state_fingerprint": current_state_fingerprint,
            },
        )
        if deployment_decision.status is not AuthorityStatus.AUTHORIZED:
            raise ActivationInvalid(f"DEPLOYMENT_AUTHORITY_BLOCKED:{deployment_decision.reason}")
        if target_mode is not runtime_state.mode:
            raise ActivationConflict("ACTIVATION_TARGET_MODE_MISMATCH")
        if target_mode is OperationalMode.LIVE:
            if runtime_state.role.value != "CHAMPION":
                raise ActivationInvalid("LIVE_REQUIRES_CHAMPION")
            if not champion_gate_authorization_id:
                raise ActivationInvalid("LIVE_CHAMPION_GATE_AUTHORITY_REQUIRED")
            try:
                ChampionGateAuthorityLedger(store).assert_valid(
                    champion_gate_authorization_id, now=now,
                    model_id=bundle.model_version, model_version=bundle.model_version,
                    candidate_id=bundle.bundle_id, promotion_id=bundle.bundle_id,
                    dependency_authority=dependency_ledger,
                )
            except ChampionGateAuthorityError as exc:
                raise ActivationInvalid(f"LIVE_CHAMPION_GATE_BLOCKED:{exc}") from exc
        try:
            assert_runtime_activation(
                runtime_state,
                policy=rollout_policy,
                allocated_risk=requested_risk,
                exposure=canary_exposure,
            )
        except ValueError as exc:
            raise ActivationInvalid(f"ROLLOUT_POLICY_BLOCKED:{exc}") from exc

        if not compatibility_authorization_id:
            raise ActivationInvalid("COMPATIBILITY_AUTHORITY_REQUIRED")
        if not artifact_integrity_authorization_id:
            raise ActivationInvalid("ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED")
        try:
            CompatibilityAuthorityLedger(store).assert_valid(
                compatibility_authorization_id,
                now=now,
                artifact_id=bundle.bundle_id,
                artifact_hashes=bundle.artifact_hashes,
                code_version=bundle.code_version,
                configuration_version=bundle.configuration_version,
                execution_model_version=bundle.execution_model_version,
                dependency_authority=dependency_ledger,
            )
        except CompatibilityAuthorityError as exc:
            raise ActivationInvalid(f"COMPATIBILITY_AUTHORITY_BLOCKED:{exc}") from exc
        if not artifacts_integrity:
            raise ActivationInvalid("ARTIFACT_INTEGRITY_BLOCKED")
        try:
            ArtifactIntegrityAuthorityLedger(store).assert_valid(
                artifact_integrity_authorization_id,
                now=now,
                artifact_id=bundle.bundle_id,
                artifact_hashes=bundle.artifact_hashes,
                dependency_authority=dependency_ledger,
            )
        except ArtifactIntegrityAuthorityError as exc:
            raise ActivationInvalid(f"ARTIFACT_INTEGRITY_AUTHORITY_BLOCKED:{exc}") from exc

        if not reconciliation_authorization_id:
            raise ActivationInvalid("RECONCILIATION_AUTHORITY_REQUIRED")
        try:
            reconciliation_ledger = ReconciliationAuthorityLedger(store)
            reconciliation_ledger.assert_activation_safe(
                reconciliation_authorization_id,
                now=now,
                scope_id=reconciliation_scope,
            )
        except ReconciliationAuthorityError as exc:
            raise ActivationInvalid(f"RECONCILIATION_BLOCKED:{exc}") from exc

        expires_at = min(approval.expires_at.astimezone(timezone.utc), proof.expires_at.astimezone(timezone.utc))
        valid_from = max(now.astimezone(timezone.utc), approval.valid_from.astimezone(timezone.utc), proof.valid_from.astimezone(timezone.utc))
        if expires_at <= valid_from:
            raise ActivationExpired("ACTIVATION_VALIDITY_WINDOW_EMPTY")

        record = DeploymentActivationRecord(
            deployment_id=deployment_id,
            bundle_id=bundle.bundle_id,
            approval_id=approval.approval_id,
            proof_id=proof.proof_id,
            target_mode=target_mode,
            valid_from=valid_from,
            expires_at=expires_at,
            state_fingerprint=current_state_fingerprint,
            recovery_proof_fingerprint=proof.fingerprint,
            recovery_readiness_authorization_id=readiness_auth.authorization_id,
            recovery_readiness_fingerprint=readiness_auth.fingerprint,
            promotion_fingerprint=promo_fp,
            truth_hash=truth.state_hash,
            authority_decision_id=deployment_decision.decision_id,
            authority_reason=deployment_decision.reason,
            requested_risk=requested_risk,
            effective_risk=deployment_decision.effective_risk,
            canary_exposure=canary_exposure,
            operator=operator,
            reconciliation_authorization_id=reconciliation_authorization_id,
            reconciliation_scope=reconciliation_scope,
            compatibility_authorization_id=compatibility_authorization_id,
            artifact_integrity_authorization_id=artifact_integrity_authorization_id,
            promotion_bundle_authorization_id=promotion_bundle_authorization_id,
            recorded_at_ms=recorded_at_ms,
            human_review_authorization_id=human_review_authorization_id,
        )
        payload = cls.payload_from_record(record)
        event_id = f"deployment-activation:authorize:{deployment_id}"
        existing = store.get(event_id)
        if existing is not None:
            if existing.event_type != cls.RECORDED:
                raise ActivationConflict("ACTIVATION_EVENT_TYPE_CONFLICT")
            existing_fp = cls.fingerprint_from_payload(existing.payload)
            if existing_fp != cls.fingerprint_from_payload(payload):
                raise ActivationConflict("ACTIVATION_ID_CONFLICT")
            restored = cls._from_payload(existing.payload)
            if not store.verify_chain():
                raise ActivationInvalid("ACTIVATION_EVENT_CHAIN_INVALID")
            return restored, False
        dependency_refs = [
            DependencyReference(
                event_id=readiness_auth and f"recovery-readiness:authorize:{readiness_auth.authorization_id}",
                expected_event_type="RECOVERY_READINESS_AUTHORIZED",
                expected_aggregate_id=proof.recovery_id,
            ),
            DependencyReference(
                event_id=f"promotion-bundle:authorize:{promotion_bundle_authorization_id}",
                expected_event_type="PROMOTION_BUNDLE_AUTHORIZED",
                expected_aggregate_id=bundle.bundle_id,
            ),
            DependencyReference(
                event_id=f"artifact-integrity:authorize:{artifact_integrity_authorization_id}",
                expected_event_type="ARTIFACT_INTEGRITY_AUTHORIZED",
                expected_aggregate_id=bundle.bundle_id,
            ),
        ]
        if compatibility_authorization_id:
            dependency_refs.append(DependencyReference(
                event_id=f"artifact-compatibility:authorize:{compatibility_authorization_id}",
                expected_event_type="ARTIFACT_COMPATIBILITY_AUTHORIZED",
                expected_aggregate_id=bundle.bundle_id,
            ))
        if reconciliation_authorization_id:
            dependency_refs.append(DependencyReference(
                event_id=f"reconciliation-evidence:record:{reconciliation_authorization_id}",
                expected_event_type="RECONCILIATION_EVIDENCE_RECORDED",
                expected_aggregate_id=reconciliation_scope,
            ))
        if target_mode is OperationalMode.LIVE and champion_gate_authorization_id:
            dependency_refs.append(DependencyReference(
                event_id=f"champion-gate:authorize:{champion_gate_authorization_id}",
                expected_event_type="CHAMPION_GATE_AUTHORIZED",
            ))
        if target_mode is OperationalMode.LIVE and human_review_authorization_id:
            dependency_refs.append(DependencyReference(
                event_id=f"human-review:approve:{human_review_authorization_id}",
                expected_event_type="HUMAN_REVIEW_APPROVED",
                expected_aggregate_id=bundle.bundle_id,
            ))
        try:
            DownstreamDependencyAuthorityLedger(store).authorize(
                authorization_id=f"deployment-activation:{deployment_id}",
                artifact_id=deployment_id,
                artifact_type="DEPLOYMENT_ACTIVATION",
                dependencies=tuple(dependency_refs),
                now_ms=recorded_at_ms,
            )
        except Exception as exc:
            raise ActivationInvalid(f"DOWNSTREAM_DEPENDENCY_BLOCKED:{exc}") from exc
        try:
            result = store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=cls.RECORDED,
                aggregate_id=deployment_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            concurrent = store.get(event_id)
            if concurrent is None:
                raise ActivationInvalid("ACTIVATION_CONCURRENT_APPEND_UNRESOLVED") from exc
            if cls.fingerprint_from_payload(concurrent.payload) != cls.fingerprint_from_payload(payload):
                raise ActivationConflict("ACTIVATION_CONCURRENT_CONFLICT") from exc
            return cls._from_payload(concurrent.payload), False
        if result.duplicate:
            restored = cls._from_payload(result.event.payload)
            if restored.fingerprint != record.fingerprint:
                raise ActivationConflict("ACTIVATION_DUPLICATE_CONFLICT")
            return restored, False
        if not store.verify_chain():
            raise ActivationInvalid("ACTIVATION_EVENT_CHAIN_INVALID")
        return record, True

    def get(self, deployment_id: str) -> DeploymentActivationRecord | None:
        if not self.store.verify_chain():
            raise ActivationInvalid("ACTIVATION_EVENT_CHAIN_INVALID")
        event = self.store.get(f"deployment-activation:authorize:{deployment_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise ActivationInvalid("ACTIVATION_EVENT_TYPE_MISMATCH")
        record = self._from_payload(event.payload)
        if record.deployment_id != deployment_id:
            raise ActivationConflict("ACTIVATION_ID_MISMATCH")
        return record

    def assert_valid(
        self,
        deployment_id: str,
        *,
        now: datetime,
        current_state_fingerprint: str,
        current_truth_hash: str,
        current_promotion_fingerprint: str,
        current_approval: Approval,
        proof_ledger: RecoveryProofLedger,
        reconciliation_ledger: ReconciliationAuthorityLedger | None = None,
        compatibility_ledger: CompatibilityAuthorityLedger | None = None,
        bundle: PromotionBundle | None = None,
        promotion_bundle_ledger: PromotionBundleAuthorityLedger | None = None,
    ) -> DeploymentActivationRecord:
        record = self.get(deployment_id)
        if record is None:
            raise ActivationInvalid("ACTIVATION_NOT_FOUND")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise ActivationExpired("ACTIVATION_EXPIRED")
        try:
            current_approval.validate(now)
        except ValueError as exc:
            raise ActivationExpired("ACTIVATION_APPROVAL_INVALID") from exc
        if record.approval_id != current_approval.approval_id:
            raise ActivationConflict("ACTIVATION_APPROVAL_ID_MISMATCH")
        if record.state_fingerprint != current_state_fingerprint:
            raise ActivationConflict("ACTIVATION_STATE_FINGERPRINT_MISMATCH")
        promotion_bundle_ledger = promotion_bundle_ledger or PromotionBundleAuthorityLedger(self.store)
        dependency_ledger = DependencyInvalidationLedger(self.store)
        if bundle is not None:
            try:
                promotion_bundle_ledger.assert_valid(
                    record.promotion_bundle_authorization_id,
                    bundle=bundle,
                    now=now,
                    dependency_authority=dependency_ledger,
                )
            except PromotionBundleAuthorityError as exc:
                raise ActivationInvalid(f"PROMOTION_BUNDLE_AUTHORITY_BLOCKED:{exc}") from exc
        compatibility_ledger = compatibility_ledger or CompatibilityAuthorityLedger(self.store)
        if bundle is not None:
            try:
                compatibility_ledger.assert_valid(
                    record.compatibility_authorization_id,
                    now=now,
                    artifact_id=bundle.bundle_id,
                    artifact_hashes=bundle.artifact_hashes,
                    code_version=bundle.code_version,
                    configuration_version=bundle.configuration_version,
                    execution_model_version=bundle.execution_model_version,
                    dependency_authority=DependencyInvalidationLedger(self.store),
                )
            except CompatibilityAuthorityError as exc:
                raise ActivationInvalid(f"COMPATIBILITY_AUTHORITY_BLOCKED:{exc}") from exc
        integrity_ledger = ArtifactIntegrityAuthorityLedger(self.store)
        if bundle is not None:
            try:
                integrity_ledger.assert_valid(
                    record.artifact_integrity_authorization_id,
                    now=now,
                    artifact_id=bundle.bundle_id,
                    artifact_hashes=bundle.artifact_hashes,
                    dependency_authority=DependencyInvalidationLedger(self.store),
                )
            except ArtifactIntegrityAuthorityError as exc:
                raise ActivationInvalid(f"ARTIFACT_INTEGRITY_AUTHORITY_BLOCKED:{exc}") from exc
        reconciliation_ledger = reconciliation_ledger or ReconciliationAuthorityLedger(self.store)
        try:
            reconciliation_ledger.assert_activation_safe(
                record.reconciliation_authorization_id,
                now=now,
                scope_id=record.reconciliation_scope,
            )
        except ReconciliationAuthorityError as exc:
            raise ActivationInvalid(f"RECONCILIATION_BLOCKED:{exc}") from exc
        if record.truth_hash != current_truth_hash:
            raise ActivationConflict("ACTIVATION_TRUTH_HASH_MISMATCH")
        if record.promotion_fingerprint != current_promotion_fingerprint:
            raise ActivationConflict("ACTIVATION_PROMOTION_FINGERPRINT_MISMATCH")
        proof = proof_ledger.assert_valid(
            record.proof_id,
            now=now,
            current_state_fingerprint=current_state_fingerprint,
        )
        if proof.fingerprint != record.recovery_proof_fingerprint:
            raise ActivationConflict("ACTIVATION_RECOVERY_PROOF_CHANGED")
        try:
            readiness_record = RecoveryReadinessLedger(self.store).assert_valid(
                record.recovery_readiness_authorization_id,
                readiness=None,
                target_mode=record.target_mode,
                proof_ledger=proof_ledger,
                now=now,
                current_state_fingerprint=current_state_fingerprint,
            )
        except RecoveryReadinessAuthorityError as exc:
            raise ActivationInvalid(f"RECOVERY_READINESS_BLOCKED:{exc}") from exc
        if readiness_record.fingerprint != record.recovery_readiness_fingerprint:
            raise ActivationConflict("ACTIVATION_RECOVERY_READINESS_CHANGED")
        return record

    def restore(self) -> dict[str, DeploymentActivationRecord]:
        if not self.store.verify_chain():
            raise ActivationInvalid("ACTIVATION_EVENT_CHAIN_INVALID")
        out: dict[str, DeploymentActivationRecord] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                continue
            record = self._from_payload(event.payload)
            if record.deployment_id in out:
                raise ActivationInvalid("DUPLICATE_ACTIVATION_ID")
            out[record.deployment_id] = record
        return out

    @staticmethod
    def _from_payload(payload: Mapping[str, Any]) -> DeploymentActivationRecord:
        try:
            record = DeploymentActivationRecord(
                deployment_id=str(payload["deployment_id"]),
                bundle_id=str(payload["bundle_id"]),
                approval_id=str(payload["approval_id"]),
                proof_id=str(payload["proof_id"]),
                target_mode=OperationalMode(str(payload["target_mode"])),
                valid_from=datetime.fromisoformat(str(payload["valid_from"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                state_fingerprint=str(payload["state_fingerprint"]),
                recovery_proof_fingerprint=str(payload["recovery_proof_fingerprint"]),
                recovery_readiness_authorization_id=str(payload.get("recovery_readiness_authorization_id", "")),
                recovery_readiness_fingerprint=str(payload.get("recovery_readiness_fingerprint", "")),
                promotion_fingerprint=str(payload["promotion_fingerprint"]),
                truth_hash=str(payload["truth_hash"]),
                authority_decision_id=str(payload["authority_decision_id"]),
                authority_reason=str(payload["authority_reason"]),
                requested_risk=Decimal(str(payload["requested_risk"])),
                effective_risk=Decimal(str(payload["effective_risk"])),
                canary_exposure=Decimal(str(payload["canary_exposure"])),
                operator=str(payload["operator"]),
                reconciliation_authorization_id=str(payload["reconciliation_authorization_id"]),
                reconciliation_scope=str(payload["reconciliation_scope"]),
                compatibility_authorization_id=str(payload["compatibility_authorization_id"]),
                artifact_integrity_authorization_id=str(payload["artifact_integrity_authorization_id"]),
                promotion_bundle_authorization_id=str(payload["promotion_bundle_authorization_id"]),
                recorded_at_ms=int(payload["recorded_at_ms"]),
                human_review_authorization_id=(str(payload["human_review_authorization_id"]) if payload.get("human_review_authorization_id") else None),
            )
            if not all((
                record.deployment_id,
                record.bundle_id,
                record.approval_id,
                record.proof_id,
                record.state_fingerprint,
                record.recovery_proof_fingerprint,
                record.recovery_readiness_authorization_id,
                record.recovery_readiness_fingerprint,
                record.promotion_fingerprint,
                record.truth_hash,
                record.authority_decision_id,
                record.operator,
                record.authority_reason,
                record.reconciliation_authorization_id,
                record.reconciliation_scope,
                record.compatibility_authorization_id,
                record.artifact_integrity_authorization_id,
                record.promotion_bundle_authorization_id,
            )):
                raise ValueError("ACTIVATION_FIELDS_REQUIRED")
            if record.valid_from.tzinfo is None or record.expires_at.tzinfo is None:
                raise ValueError("ACTIVATION_TIMEZONE_REQUIRED")
            if record.expires_at <= record.valid_from:
                raise ValueError("ACTIVATION_WINDOW_INVALID")
            if any(v < 0 or not v.is_finite() for v in (record.requested_risk, record.effective_risk, record.canary_exposure)):
                raise ValueError("ACTIVATION_RISK_INVALID")
            if record.recorded_at_ms < 0:
                raise ValueError("ACTIVATION_TIMESTAMP_INVALID")
            return record
        except Exception as exc:
            raise ActivationInvalid("INVALID_ACTIVATION_PAYLOAD") from exc


class AuthorizedDeploymentController:
    """Production-facing deployment boundary requiring durable V3.25 activation authority."""

    def __init__(self, *, orchestrator: DeploymentOrchestrator, activation_ledger: DeploymentActivationLedger, proof_ledger: RecoveryProofLedger) -> None:
        self.orchestrator = orchestrator
        self.activation_ledger = activation_ledger
        self.proof_ledger = proof_ledger

    def activate_canary(
        self,
        state: LegacyDeploymentState,
        *,
        now: datetime,
        now_ns: int,
        current_state_fingerprint: str,
        current_truth_hash: str,
    ) -> LegacyDeploymentState:
        if state.phase is not DeploymentPhase.CANARY:
            raise ActivationInvalid("ACTIVATION_REQUIRES_CANARY_PHASE")
        record = require_authorized_activation(
            self.activation_ledger,
            state.request.deployment_id,
            now=now,
            current_state_fingerprint=current_state_fingerprint,
            current_truth_hash=current_truth_hash,
            current_promotion_fingerprint=DeploymentActivationLedger.promotion_fingerprint(
                bundle=state.request.bundle, approval=state.request.approval, gates=state.request.gates,
                scope=state.request.scope, evidence_valid=state.request.evidence_valid,
                compatibility_valid=state.request.compatibility_valid, artifacts_integrity=state.request.artifacts_integrity,
            ),
            current_approval=state.request.approval,
            proof_ledger=self.proof_ledger,
            bundle=state.request.bundle,
        )
        if record.target_mode is not OperationalMode.CANARY:
            raise ActivationConflict("CANARY_ACTIVATION_TARGET_MISMATCH")
        if record.bundle_id != state.request.bundle.bundle_id or record.approval_id != state.request.approval.approval_id:
            raise ActivationConflict("ACTIVATION_BUNDLE_OR_APPROVAL_MISMATCH")
        if record.compatibility_authorization_id != state.request.compatibility_authorization_id:
            raise ActivationConflict("ACTIVATION_COMPATIBILITY_AUTHORITY_MISMATCH")
        if record.artifact_integrity_authorization_id != state.request.artifact_integrity_authorization_id:
            raise ActivationConflict("ACTIVATION_ARTIFACT_INTEGRITY_AUTHORITY_MISMATCH")
        if record.promotion_bundle_authorization_id != state.request.promotion_bundle_authorization_id:
            raise ActivationConflict("ACTIVATION_PROMOTION_BUNDLE_AUTHORITY_MISMATCH")
        if record.requested_risk != state.request.requested_risk:
            raise ActivationConflict("ACTIVATION_REQUESTED_RISK_MISMATCH")
        if state.allocated_risk > record.effective_risk:
            raise ActivationInvalid("ACTIVATION_WOULD_INCREASE_AUTHORIZED_RISK")
        capability = _issue_activation_capability(
            deployment_id=record.deployment_id,
            activation_fingerprint=record.fingerprint,
            target_mode=record.target_mode.value,
            effective_risk=record.effective_risk,
            valid_from=record.valid_from,
            expires_at=record.expires_at,
        )
        with activation_capability_context(capability):
            return self.orchestrator.activate(state, now=now, now_ns=now_ns)


def require_authorized_activation(
    ledger: DeploymentActivationLedger,
    deployment_id: str,
    *,
    now: datetime,
    current_state_fingerprint: str,
    current_truth_hash: str,
    current_promotion_fingerprint: str,
    current_approval: Approval,
    proof_ledger: RecoveryProofLedger,
    bundle: PromotionBundle | None = None,
) -> DeploymentActivationRecord:
    """Machine-checkable production activation gate."""
    return ledger.assert_valid(
        deployment_id,
        now=now,
        current_state_fingerprint=current_state_fingerprint,
        current_truth_hash=current_truth_hash,
        current_promotion_fingerprint=current_promotion_fingerprint,
        current_approval=current_approval,
        proof_ledger=proof_ledger,
        bundle=bundle,
    )

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationBlocked, DependencyInvalidationLedger
from trading_platform.v359.human_review import HumanReviewAuthorityInvalid, HumanReviewAuthorityLedger
from trading_platform.v395.trust_anchor_attestation import ReviewerTrustAnchorV395
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError, EvidenceSnapshotAuthorityLedger
from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityError, PromotionBundleAuthorityLedger
from trading_platform.v408.gate_promotion import CriticalPromotionGateErrorV408, GatePromotionAuthorizationLedgerV408


class CriticalPromotionErrorV398(ValueError):
    __test__ = False


class CriticalPromotionConflictV398(CriticalPromotionErrorV398):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class ExternalRollbackAttestationV398:
    attestation_id: str
    scope: str
    bundle_id: str
    evidence_snapshot_id: str
    rollback_target: str
    release_artifact_hash: str
    rollback_evidence_ref: str
    recovery_proof_ref: str
    rollback_executed_at_ms: int
    residual_risk_zero: bool
    trading_blocked_after_rollback: bool
    reviewer_id: str
    reviewer_key_id: str
    operator_id: str
    reviewed_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "scope": self.scope,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "rollback_target": self.rollback_target,
            "release_artifact_hash": self.release_artifact_hash,
            "rollback_evidence_ref": self.rollback_evidence_ref,
            "recovery_proof_ref": self.recovery_proof_ref,
            "rollback_executed_at_ms": self.rollback_executed_at_ms,
            "residual_risk_zero": self.residual_risk_zero,
            "trading_blocked_after_rollback": self.trading_blocked_after_rollback,
            "reviewer_id": self.reviewer_id,
            "reviewer_key_id": self.reviewer_key_id,
            "operator_id": self.operator_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def fingerprint(self) -> str:
        return sha256(_canonical(self.body_for_hash())).hexdigest()

    def signature_bytes(self) -> bytes:
        try:
            raw = b64decode(self.signature_b64.encode("ascii"), validate=True)
        except Exception as exc:
            raise CriticalPromotionErrorV398("ROLLBACK_SIGNATURE_BASE64_INVALID") from exc
        if not raw:
            raise CriticalPromotionErrorV398("ROLLBACK_SIGNATURE_EMPTY")
        return raw

    def validate(self, *, bundle: PromotionBundle, now_ms: int, reviewer_anchor: ReviewerTrustAnchorV395) -> None:
        if self.scope != "PRODUCTION_CRITICAL":
            raise CriticalPromotionErrorV398("ROLLBACK_SCOPE_INVALID")
        if self.bundle_id != bundle.bundle_id or self.evidence_snapshot_id != bundle.evidence_snapshot_id:
            raise CriticalPromotionErrorV398("ROLLBACK_BUNDLE_BINDING_MISMATCH")
        if self.rollback_target != bundle.rollback_target:
            raise CriticalPromotionErrorV398("ROLLBACK_TARGET_MISMATCH")
        if self.release_artifact_hash != bundle.content_hash:
            raise CriticalPromotionErrorV398("ROLLBACK_RELEASE_HASH_MISMATCH")
        if self.decision != "ACCEPT":
            raise CriticalPromotionErrorV398("ROLLBACK_ATTESTATION_NOT_ACCEPTED")
        for ref in (self.rollback_evidence_ref, self.recovery_proof_ref):
            if not ref or ref.startswith(("demo:", "synthetic:", "fixture:", "mock:")):
                raise CriticalPromotionErrorV398("ROLLBACK_EXTERNAL_EVIDENCE_REQUIRED")
        if self.reviewer_id == self.operator_id:
            raise CriticalPromotionErrorV398("ROLLBACK_REVIEWER_OPERATOR_CONFLICT")
        if not (self.residual_risk_zero and self.trading_blocked_after_rollback):
            raise CriticalPromotionErrorV398("ROLLBACK_POSTCONDITION_INCOMPLETE")
        if self.rollback_executed_at_ms < 0 or self.reviewed_at_ms < 0:
            raise CriticalPromotionErrorV398("ROLLBACK_TIMESTAMP_INVALID")
        if not (self.reviewed_at_ms < self.expires_at_ms and self.reviewed_at_ms <= now_ms < self.expires_at_ms):
            raise CriticalPromotionErrorV398("ROLLBACK_ATTESTATION_EXPIRED")
        reviewer_anchor.validate(scope=self.scope, now_ms=now_ms)
        if self.reviewer_key_id != reviewer_anchor.reviewer_key_id:
            raise CriticalPromotionErrorV398("ROLLBACK_REVIEWER_KEY_ID_MISMATCH")
        signature = self.signature_bytes()
        if sha256(signature).hexdigest() != self.signature_hash:
            raise CriticalPromotionErrorV398("ROLLBACK_SIGNATURE_HASH_MISMATCH")
        try:
            Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(signature, _canonical(self.body_for_hash()))
        except InvalidSignature as exc:
            raise CriticalPromotionErrorV398("ROLLBACK_REVIEWER_SIGNATURE_INVALID") from exc


@dataclass(frozen=True)
class CriticalPromotionDecisionV398:
    allowed: bool
    reason: str
    decision_id: str
    bundle_id: str
    readiness_id: str
    human_review_id: str
    rollback_attestation_id: str
    status: str


class CriticalPromotionReadinessAuthorityV398:
    EVENT_TYPE = "CRITICAL_PROMOTION_READINESS_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def _require_event(self, event_id: str, reason: str):
        event = self.store.get(event_id)
        if event is None:
            raise CriticalPromotionErrorV398(reason)
        return event

    def admit(
        self,
        *,
        decision_id: str,
        bundle: PromotionBundle,
        approval: Approval,
        promotion_bundle_authorization_id: str,
        human_review_id: str,
        readiness_id: str,
        dr_attestation_id: str,
        trust_anchor_attestation_id: str,
        rollback_attestation: ExternalRollbackAttestationV398,
        rollback_reviewer_anchor: ReviewerTrustAnchorV395,
        dependency_authority: DependencyInvalidationLedger,
        now: datetime,
        now_ms: int,
    ) -> CriticalPromotionDecisionV398:
        try:
            if not decision_id:
                raise CriticalPromotionErrorV398("CRITICAL_PROMOTION_DECISION_ID_REQUIRED")
            if bundle.scope.get("environment") != "PRODUCTION":
                raise CriticalPromotionErrorV398("PRODUCTION_SCOPE_REQUIRED")
            if bundle.scope.get("criticality") != "CRITICAL":
                raise CriticalPromotionErrorV398("CRITICAL_SCOPE_REQUIRED")
            if len(set(approval.approved_by)) < 2:
                raise CriticalPromotionErrorV398("DUAL_APPROVAL_REQUIRED")
            approval.validate(now)
            bundle.validate()
            if not self.store.verify_chain():
                raise CriticalPromotionErrorV398("EVENT_CHAIN_INVALID")

            self._require_event(f"trust-anchor-attestation:{trust_anchor_attestation_id}:accepted", "TRUST_ANCHOR_ATTESTATION_REQUIRED")
            readiness_event = self._require_event(f"security-monitoring-readiness:{readiness_id}:accepted", "SECURITY_MONITORING_READINESS_REQUIRED")
            if str(readiness_event.payload.get("release_artifact_hash")) != bundle.content_hash:
                raise CriticalPromotionErrorV398("READINESS_RELEASE_HASH_MISMATCH")
            self._require_event(f"external-dr-attestation:{dr_attestation_id}:accepted", "DR_ATTESTATION_REQUIRED")

            # Critical promotion must bind to a durable Evidence Snapshot authorization.
            # A live snapshot identifier or an otherwise-valid bundle is insufficient: the
            # exact snapshot must be present, unexpired, promotion/bundle bound, and fresh
            # against the dependency invalidation ledger.
            try:
                EvidenceSnapshotAuthorityLedger(self.store).assert_valid(
                    bundle.evidence_snapshot_id,
                    now=now,
                    promotion_id=bundle.bundle_id,
                    bundle_id=bundle.bundle_id,
                    model_version=bundle.model_version,
                    required_gate_ids=bundle.gate_results,
                    required_artifact_hashes=bundle.artifact_hashes,
                    required_versions=(
                        bundle.strategy_version, bundle.model_version, bundle.feature_version,
                        bundle.target_version, bundle.configuration_version,
                        bundle.execution_model_version, bundle.code_version,
                    ),
                    approval_id=bundle.approval_id,
                    requested_scope=bundle.scope,
                    dependency_authority=dependency_authority,
                )
            except EvidenceSnapshotAuthorityError as exc:
                reason = str(exc)
                if "STALE_AFTER_INVALIDATION" in reason:
                    raise CriticalPromotionErrorV398("EVIDENCE_SNAPSHOT_STALE_AFTER_INVALIDATION") from exc
                raise CriticalPromotionErrorV398("EVIDENCE_SNAPSHOT_AUTHORITY_REQUIRED") from exc

            try:
                PromotionBundleAuthorityLedger(self.store).assert_valid(
                    promotion_bundle_authorization_id,
                    bundle=bundle,
                    now=now,
                    dependency_authority=dependency_authority,
                )
            except PromotionBundleAuthorityError as exc:
                raise CriticalPromotionErrorV398("PROMOTION_BUNDLE_AUTHORITY_REQUIRED") from exc

            # Every gate in the bundle must have a durable, exact gate authorization
            # and remain reusable from its own dependency checkpoint. A prior PASS
            # gate is never sufficient by identifier alone.
            try:
                gate_ledger = GatePromotionAuthorizationLedgerV408(self.store)
                for gate_id in bundle.gate_results:
                    gate_ledger.assert_registered_reusable(gate_id, dependency_authority, now_ms)
            except CriticalPromotionGateErrorV408 as exc:
                raise CriticalPromotionErrorV398("CRITICAL_PROMOTION_GATE_REVALIDATION_REQUIRED") from exc

            try:
                human_review = HumanReviewAuthorityLedger(self.store).assert_valid(
                    human_review_id,
                    bundle=bundle,
                    approval=approval,
                    now=now,
                    dependency_authority=dependency_authority,
                )
            except HumanReviewAuthorityInvalid as exc:
                raise CriticalPromotionErrorV398("INDEPENDENT_HUMAN_REVIEW_REQUIRED") from exc

            if set(human_review.reviewers) & set(approval.approved_by):
                raise CriticalPromotionErrorV398("HUMAN_REVIEWER_APPROVER_CONFLICT")
            rollback_attestation.validate(bundle=bundle, now_ms=now_ms, reviewer_anchor=rollback_reviewer_anchor)

            dependencies = (
                bundle.bundle_id,
                bundle.evidence_snapshot_id,
                promotion_bundle_authorization_id,
                human_review_id,
                readiness_id,
                dr_attestation_id,
                trust_anchor_attestation_id,
                dr_attestation_id,
                rollback_attestation.attestation_id,
                rollback_attestation.rollback_target,
                bundle.content_hash,
            )
            try:
                dependency_authority.assert_clear(dependencies)
            except DependencyInvalidationBlocked as exc:
                raise CriticalPromotionErrorV398("CRITICAL_PROMOTION_DEPENDENCY_BLOCKED") from exc

            event_id = f"critical-promotion-readiness:{decision_id}:accepted"
            payload = {
                "decision_id": decision_id,
                "bundle_id": bundle.bundle_id,
                "approval_id": approval.approval_id,
                "promotion_bundle_authorization_id": promotion_bundle_authorization_id,
                "human_review_id": human_review_id,
                "readiness_id": readiness_id,
                "dr_attestation_id": dr_attestation_id,
                "trust_anchor_attestation_id": trust_anchor_attestation_id,
                "rollback_attestation_id": rollback_attestation.attestation_id,
                "rollback_fingerprint": rollback_attestation.fingerprint(),
                "reviewers": list(human_review.reviewers),
                "approvers": list(approval.approved_by),
                "status": "VERIFIED",
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(event_id=event_id, occurred_at_ms=now_ms, event_type=self.EVENT_TYPE, aggregate_id=bundle.bundle_id, payload=payload)
            elif dict(existing.payload) != payload:
                raise CriticalPromotionConflictV398("CRITICAL_PROMOTION_EVENT_ID_CONFLICT")
            return CriticalPromotionDecisionV398(True, "CRITICAL_PROMOTION_READINESS_ACCEPTED", decision_id, bundle.bundle_id, readiness_id, human_review_id, rollback_attestation.attestation_id, "VERIFIED")
        except CriticalPromotionErrorV398 as exc:
            return CriticalPromotionDecisionV398(False, str(exc), decision_id, bundle.bundle_id, readiness_id, human_review_id, rollback_attestation.attestation_id, "REJECTED")

    def get(self, decision_id: str):
        return self.store.get(f"critical-promotion-readiness:{decision_id}:accepted")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

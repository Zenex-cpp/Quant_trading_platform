from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationError,
    DependencyInvalidationLedger,
)
from trading_platform.v359.human_review import (
    HumanReviewAuthorityInvalid,
    HumanReviewAuthorityLedger,
)
from trading_platform.v360.readiness_evidence import (
    ProductionReadinessAssessor,
    ProductionReadinessAssessment,
    ReadinessEvidenceLedger,
    REQUIRED_EVIDENCE_CLASSES,
)
from trading_platform.v408.gate_promotion import (
    CriticalPromotionGateDecisionV408,
    CriticalPromotionGatePreflightV408,
    CriticalPromotionGateErrorV408,
)
from trading_platform.gates.contracts import Gate


class ProductionReadinessAuthorityErrorV409(ValueError):
    __test__ = False


@dataclass(frozen=True)
class ProductionReadinessRecordV409:
    readiness_id: str
    bundle_id: str
    evidence_snapshot_id: str
    application_preflight_reason: str
    application_preflight_fingerprint: str
    evidence_ids: tuple[str, ...]
    human_review_id: str
    approval_id: str
    dependency_checkpoint: int
    assessed_at_ms: int

    @property
    def fingerprint(self) -> str:
        return sha256_json({
            "readiness_id": self.readiness_id,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "application_preflight_reason": self.application_preflight_reason,
            "application_preflight_fingerprint": self.application_preflight_fingerprint,
            "evidence_ids": list(self.evidence_ids),
            "human_review_id": self.human_review_id,
            "approval_id": self.approval_id,
            "dependency_checkpoint": self.dependency_checkpoint,
            "assessed_at_ms": self.assessed_at_ms,
        })


@dataclass(frozen=True)
class ProductionReadinessDecisionV409:
    allowed: bool
    status: str
    reason: str
    bundle_id: str
    missing_evidence: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    readiness_id: str | None
    human_review_id: str | None
    approval_id: str
    application_preflight: CriticalPromotionGateDecisionV408 | None

    @property
    def production_ready(self) -> bool:
        return self.allowed and self.status == "PRODUCTION_READY"


class ProductionReadinessAuthorityV409:
    """Single fail-closed binding boundary for §174/§176 production readiness.

    The authority never fabricates external evidence, approval, Testnet events,
    security review, DR proof, or infrastructure evidence. It only accepts
    evidence that is already marked externally sourced and independently
    verified by the existing readiness/evidence authorities.
    """

    EVENT_TYPE = "PRODUCTION_READINESS_VERIFIED_V409"

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.dependency_authority.store is not self.store:
            raise ProductionReadinessAuthorityErrorV409("SHARED_EVENT_STORE_REQUIRED")
        self.evidence_ledger = ReadinessEvidenceLedger(self.store)
        self.evidence_assessor = ProductionReadinessAssessor(self.evidence_ledger)
        self.human_review = HumanReviewAuthorityLedger(self.store)
        self.preflight = CriticalPromotionGatePreflightV408(
            store=self.store,
            dependency_authority=self.dependency_authority,
        )

    @staticmethod
    def _utc_ms(now: datetime) -> int:
        if now.tzinfo is None:
            raise ProductionReadinessAuthorityErrorV409("NOW_TIMEZONE_REQUIRED")
        return int(now.astimezone(timezone.utc).timestamp() * 1000)

    @staticmethod
    def _preflight_fingerprint(decision: CriticalPromotionGateDecisionV408) -> str:
        body = {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "gate_ids": list(decision.gate_ids),
            "revalidated_gate_ids": list(decision.revalidated_gate_ids),
            "stale_gate_ids": list(decision.stale_gate_ids),
            "snapshot_decision": {
                "allowed": decision.snapshot_decision.allowed,
                "reason": decision.snapshot_decision.reason,
                "snapshot_id": decision.snapshot_decision.snapshot_id,
                "bundle_id": decision.snapshot_decision.bundle_id,
            },
        }
        return sha256_json(body)

    @staticmethod
    def _bundle_dependencies(bundle: PromotionBundle, evidence_ids: tuple[str, ...], human_review_id: str) -> tuple[str, ...]:
        return tuple(sorted(set(
            (
                bundle.bundle_id,
                bundle.evidence_snapshot_id,
                *bundle.gate_results,
                *bundle.artifact_hashes,
                bundle.strategy_version,
                bundle.model_version,
                bundle.feature_version,
                bundle.target_version,
                bundle.configuration_version,
                bundle.execution_model_version,
                bundle.code_version,
                bundle.approval_id,
                bundle.rollback_target,
                bundle.content_hash,
                *evidence_ids,
                human_review_id,
            )
        )))

    def assess(
        self,
        *,
        bundle: PromotionBundle,
        gates: tuple[Gate, ...],
        approval: Approval,
        human_review_id: str,
        scope: str,
        now: datetime,
        assessment_id: str,
        record: bool = True,
    ) -> ProductionReadinessDecisionV409:
        try:
            bundle.validate()
        except ValueError as exc:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"BUNDLE:{exc}", bundle.bundle_id,
                tuple(REQUIRED_EVIDENCE_CLASSES), (), None, human_review_id, bundle.approval_id, None,
            )

        try:
            approval.validate(now)
        except ValueError as exc:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"APPROVAL:{exc}", bundle.bundle_id,
                tuple(REQUIRED_EVIDENCE_CLASSES), (), None, human_review_id, bundle.approval_id, None,
            )

        initial_checkpoint = self.dependency_authority.checkpoint()
        try:
            self.dependency_authority.assert_clear(self._bundle_dependencies(bundle, (), human_review_id))
        except (DependencyInvalidationBlocked, DependencyInvalidationError) as exc:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"DEPENDENCY:{type(exc).__name__}", bundle.bundle_id,
                tuple(REQUIRED_EVIDENCE_CLASSES), (), None, human_review_id, bundle.approval_id, None,
            )

        preflight = self.preflight.check(bundle=bundle, gates=gates, now=now)
        if not preflight.allowed:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"APPLICATION_PREFLIGHT:{preflight.reason}", bundle.bundle_id,
                tuple(REQUIRED_EVIDENCE_CLASSES), (), None, human_review_id, bundle.approval_id, preflight,
            )

        try:
            human = self.human_review.assert_valid(
                human_review_id,
                bundle=bundle,
                approval=approval,
                now=now,
                dependency_authority=self.dependency_authority,
            )
        except HumanReviewAuthorityInvalid as exc:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"HUMAN_REVIEW:{exc}", bundle.bundle_id,
                tuple(REQUIRED_EVIDENCE_CLASSES), (), None, human_review_id, bundle.approval_id, preflight,
            )

        assessment: ProductionReadinessAssessment = self.evidence_assessor.assess(
            assessment_id=assessment_id,
            scope=scope,
            now_ms=self._utc_ms(now),
        )
        if not assessment.production_ready:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", "EXTERNAL_OPERATIONAL_EVIDENCE_INCOMPLETE", bundle.bundle_id,
                tuple(assessment.missing), tuple(assessment.evidence_ids), None,
                human_review.review_id, approval.approval_id, preflight,
            )

        evidence_ids = tuple(sorted(assessment.evidence_ids))
        dependencies = self._bundle_dependencies(bundle, evidence_ids, human.review_id)
        try:
            self.dependency_authority.assert_clear(dependencies)
            self.dependency_authority.assert_unchanged_since(initial_checkpoint, dependencies)
        except (DependencyInvalidationBlocked, DependencyInvalidationError) as exc:
            return ProductionReadinessDecisionV409(
                False, "BLOCKED", f"DEPENDENCY_REVALIDATION:{type(exc).__name__}", bundle.bundle_id,
                tuple(assessment.missing), evidence_ids, None, human.review_id,
                approval.approval_id, preflight,
            )

        readiness_id = f"production-readiness:{assessment_id}"
        record_obj = ProductionReadinessRecordV409(
            readiness_id=readiness_id,
            bundle_id=bundle.bundle_id,
            evidence_snapshot_id=bundle.evidence_snapshot_id,
            application_preflight_reason=preflight.reason,
            application_preflight_fingerprint=self._preflight_fingerprint(preflight),
            evidence_ids=evidence_ids,
            human_review_id=human.review_id,
            approval_id=approval.approval_id,
            dependency_checkpoint=initial_checkpoint,
            assessed_at_ms=self._utc_ms(now),
        )
        if record:
            self._persist(record_obj)

        return ProductionReadinessDecisionV409(
            True,
            "PRODUCTION_READY",
            "PRODUCTION_READINESS_VERIFIED",
            bundle.bundle_id,
            (),
            evidence_ids,
            readiness_id,
            human.review_id,
            approval.approval_id,
            preflight,
        )

    def _persist(self, record: ProductionReadinessRecordV409) -> None:
        payload = {
            "readiness_id": record.readiness_id,
            "bundle_id": record.bundle_id,
            "evidence_snapshot_id": record.evidence_snapshot_id,
            "application_preflight_reason": record.application_preflight_reason,
            "application_preflight_fingerprint": record.application_preflight_fingerprint,
            "evidence_ids": list(record.evidence_ids),
            "human_review_id": record.human_review_id,
            "approval_id": record.approval_id,
            "dependency_checkpoint": record.dependency_checkpoint,
            "assessed_at_ms": record.assessed_at_ms,
            "record_fingerprint": record.fingerprint,
            "source": "V409_OPERATIONAL_READINESS_BINDING",
        }
        existing = self.store.get(record.readiness_id)
        if existing is not None:
            if existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
                raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_RECORD_CONFLICT")
            return
        self.store.append(
            event_id=record.readiness_id,
            occurred_at_ms=record.assessed_at_ms,
            event_type=self.EVENT_TYPE,
            aggregate_id=record.bundle_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise ProductionReadinessAuthorityErrorV409("EVENT_CHAIN_INVALID_AFTER_READINESS_RECORD")

    def get(self, readiness_id: str) -> ProductionReadinessRecordV409 | None:
        event = self.store.get(readiness_id)
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        p = event.payload
        return ProductionReadinessRecordV409(
            readiness_id=str(p["readiness_id"]),
            bundle_id=str(p["bundle_id"]),
            evidence_snapshot_id=str(p["evidence_snapshot_id"]),
            application_preflight_reason=str(p["application_preflight_reason"]),
            application_preflight_fingerprint=str(p["application_preflight_fingerprint"]),
            evidence_ids=tuple(str(v) for v in p["evidence_ids"]),
            human_review_id=str(p["human_review_id"]),
            approval_id=str(p["approval_id"]),
            dependency_checkpoint=int(p["dependency_checkpoint"]),
            assessed_at_ms=int(p["assessed_at_ms"]),
        )

    def assert_verified(
        self,
        readiness_id: str,
        *,
        bundle: PromotionBundle,
        gates: tuple[Gate, ...],
        approval: Approval,
        scope: str,
        now: datetime,
    ) -> ProductionReadinessRecordV409:
        record = self.get(readiness_id)
        if record is None:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_RECORD_NOT_FOUND")
        if record.bundle_id != bundle.bundle_id or record.evidence_snapshot_id != bundle.evidence_snapshot_id:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_BUNDLE_MISMATCH")
        if record.approval_id != approval.approval_id:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_APPROVAL_MISMATCH")
        now_ms = self._utc_ms(now)
        if now_ms < record.assessed_at_ms:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_TIME_TRAVEL")
        if not self.store.verify_chain():
            raise ProductionReadinessAuthorityErrorV409("EVENT_CHAIN_INVALID")
        try:
            self.dependency_authority.assert_clear(
                self._bundle_dependencies(bundle, record.evidence_ids, record.human_review_id)
            )
            self.dependency_authority.assert_unchanged_since(
                record.dependency_checkpoint,
                self._bundle_dependencies(bundle, record.evidence_ids, record.human_review_id),
            )
        except DependencyInvalidationBlocked as exc:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_STALE_AFTER_INVALIDATION") from exc
        except DependencyInvalidationError as exc:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_REQUIRES_REVALIDATION") from exc

        decision = self.assess(
            bundle=bundle,
            gates=gates,
            approval=approval,
            human_review_id=record.human_review_id,
            scope=scope,
            now=now,
            assessment_id=readiness_id.removeprefix("production-readiness:"),
            record=False,
        )
        if not decision.production_ready:
            raise ProductionReadinessAuthorityErrorV409(
                "PRODUCTION_READINESS_REVALIDATION_FAILED:" + decision.reason
            )
        if self._preflight_fingerprint(decision.application_preflight) != record.application_preflight_fingerprint:
            raise ProductionReadinessAuthorityErrorV409("PRODUCTION_READINESS_PREFLIGHT_FINGERPRINT_CHANGED")
        return record

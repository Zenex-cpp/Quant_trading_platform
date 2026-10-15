from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger, PromotionBundleAuthorityError


class HumanReviewAuthorityError(RuntimeError):
    pass


class HumanReviewAuthorityInvalid(HumanReviewAuthorityError):
    pass


class HumanReviewAuthorityConflict(HumanReviewAuthorityError):
    pass


def _hash(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class HumanReviewPackage:
    review_id: str
    bundle_id: str
    evidence_snapshot_id: str
    promotion_bundle_authorization_id: str
    approval_id: str
    reviewers: tuple[str, ...]
    known_limitations: tuple[str, ...]
    rollback_target: str
    open_incidents: tuple[str, ...]
    revalidation_status: str
    scope: Mapping[str, str]
    reviewed_at: datetime
    valid_from: datetime
    expires_at: datetime

    @property
    def fingerprint(self) -> str:
        return _hash({
            "review_id": self.review_id,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "promotion_bundle_authorization_id": self.promotion_bundle_authorization_id,
            "approval_id": self.approval_id,
            "reviewers": list(self.reviewers),
            "known_limitations": list(self.known_limitations),
            "rollback_target": self.rollback_target,
            "open_incidents": list(self.open_incidents),
            "revalidation_status": self.revalidation_status,
            "scope": dict(self.scope),
            "reviewed_at": self.reviewed_at.astimezone(timezone.utc).isoformat(),
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
        })


@dataclass(frozen=True)
class HumanReviewAuthorization:
    review_id: str
    bundle_id: str
    evidence_snapshot_id: str
    promotion_bundle_authorization_id: str
    approval_id: str
    package_fingerprint: str
    valid_from: datetime
    expires_at: datetime
    reviewers: tuple[str, ...]
    recorded_at_ms: int
    dependency_checkpoint_sequence: int
    dependency_keys: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return _hash({
            "review_id": self.review_id,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "promotion_bundle_authorization_id": self.promotion_bundle_authorization_id,
            "approval_id": self.approval_id,
            "package_fingerprint": self.package_fingerprint,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewers": list(self.reviewers),
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
            "dependency_keys": list(self.dependency_keys),
        })


class HumanReviewAuthorityLedger:
    EVENT_TYPE = "HUMAN_REVIEW_APPROVED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _window(valid_from: datetime, expires_at: datetime) -> tuple[datetime, datetime]:
        if valid_from.tzinfo is None or expires_at.tzinfo is None or expires_at <= valid_from:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_VALIDITY_WINDOW_INVALID")
        return valid_from.astimezone(timezone.utc), expires_at.astimezone(timezone.utc)

    @staticmethod
    def _dependencies(bundle: PromotionBundle, package: HumanReviewPackage) -> tuple[str, ...]:
        return (
            bundle.bundle_id,
            bundle.evidence_snapshot_id,
            package.promotion_bundle_authorization_id,
            package.approval_id,
            bundle.rollback_target,
            bundle.content_hash,
            *bundle.gate_results,
            *bundle.artifact_hashes,
            bundle.strategy_version,
            bundle.model_version,
            bundle.feature_version,
            bundle.target_version,
            bundle.configuration_version,
            bundle.execution_model_version,
            bundle.code_version,
        )

    @classmethod
    def authorize(
        cls,
        *,
        package: HumanReviewPackage,
        bundle: PromotionBundle,
        approval: Approval,
        promotion_bundle_authorization_id: str,
        dependency_authority: DependencyInvalidationLedger,
        recorded_at_ms: int,
        store: EventStore | None = None,
    ) -> tuple[HumanReviewAuthorization, bool]:
        if not package.review_id or not package.reviewers:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_IDENTIFIERS_REQUIRED")
        if not package.known_limitations:
            raise HumanReviewAuthorityInvalid("KNOWN_LIMITATIONS_REQUIRED")
        if package.open_incidents:
            raise HumanReviewAuthorityInvalid("OPEN_CRITICAL_INCIDENTS_BLOCK_REVIEW")
        if package.revalidation_status != "PASS":
            raise HumanReviewAuthorityInvalid("REVALIDATION_STATUS_NOT_PASS")
        if package.rollback_target != bundle.rollback_target:
            raise HumanReviewAuthorityInvalid("ROLLBACK_TARGET_MISMATCH")
        if package.bundle_id != bundle.bundle_id:
            raise HumanReviewAuthorityInvalid("REVIEW_BUNDLE_MISMATCH")
        if package.evidence_snapshot_id != bundle.evidence_snapshot_id:
            raise HumanReviewAuthorityInvalid("REVIEW_EVIDENCE_MISMATCH")
        if package.promotion_bundle_authorization_id != promotion_bundle_authorization_id:
            raise HumanReviewAuthorityInvalid("REVIEW_PROMOTION_AUTHORITY_MISMATCH")
        if package.approval_id != approval.approval_id or bundle.approval_id != approval.approval_id:
            raise HumanReviewAuthorityInvalid("REVIEW_APPROVAL_MISMATCH")
        if recorded_at_ms < 0:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_TIMESTAMP_INVALID")
        start, end = cls._window(package.valid_from, package.expires_at)
        approval.validate(start)
        bundle.validate()
        store = store or dependency_authority.store
        if store is not dependency_authority.store:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_AUTHORITY_STORE_MISMATCH")
        if not store.verify_chain():
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_EVENT_CHAIN_INVALID")
        try:
            promotion_auth = PromotionBundleAuthorityLedger(store).assert_valid(
                promotion_bundle_authorization_id,
                bundle=bundle,
                now=start,
                dependency_authority=dependency_authority,
            )
        except PromotionBundleAuthorityError as exc:
            raise HumanReviewAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_REQUIRED") from exc

        # §186 / V3.59 independent-review boundary: a human reviewer must not
        # be the same identity that authorized the upstream Promotion Bundle
        # or an approver on the Approval record. This prevents a single actor
        # from supplying both upstream authorization and independent review.
        upstream_actor = promotion_auth.reviewer
        approval_actors = set(str(actor) for actor in approval.approved_by)
        conflicting_reviewers = sorted(
            set(str(reviewer) for reviewer in package.reviewers)
            & ({upstream_actor} | approval_actors)
        )
        if conflicting_reviewers:
            raise HumanReviewAuthorityInvalid(
                "INDEPENDENT_HUMAN_REVIEW_REQUIRED:" + ",".join(conflicting_reviewers)
            )

        dependencies = cls._dependencies(bundle, package)
        try:
            dependency_authority.assert_clear(dependencies)
        except DependencyInvalidationBlocked as exc:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_DEPENDENCY_BLOCKED") from exc
        checkpoint = dependency_authority.checkpoint()
        package_fp = package.fingerprint
        record = HumanReviewAuthorization(
            review_id=package.review_id,
            bundle_id=bundle.bundle_id,
            evidence_snapshot_id=bundle.evidence_snapshot_id,
            promotion_bundle_authorization_id=promotion_bundle_authorization_id,
            approval_id=approval.approval_id,
            package_fingerprint=package_fp,
            valid_from=start,
            expires_at=end,
            reviewers=tuple(package.reviewers),
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=checkpoint,
            dependency_keys=dependencies,
        )
        event_id = f"human-review:approve:{package.review_id}"
        existing = store.get(event_id)
        if existing:
            if existing.event_type != cls.EVENT_TYPE:
                raise HumanReviewAuthorityConflict("HUMAN_REVIEW_EVENT_TYPE_CONFLICT")
            restored = cls._from_event(existing)
            if restored.package_fingerprint != package_fp or restored.bundle_id != bundle.bundle_id:
                raise HumanReviewAuthorityConflict("HUMAN_REVIEW_ID_CONFLICT")
            return restored, False
        payload = {
            "review_id": record.review_id,
            "bundle_id": record.bundle_id,
            "evidence_snapshot_id": record.evidence_snapshot_id,
            "promotion_bundle_authorization_id": record.promotion_bundle_authorization_id,
            "approval_id": record.approval_id,
            "package_fingerprint": record.package_fingerprint,
            "valid_from": record.valid_from.isoformat(),
            "expires_at": record.expires_at.isoformat(),
            "reviewers": list(record.reviewers),
            "recorded_at_ms": record.recorded_at_ms,
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
            "dependency_keys": list(record.dependency_keys),
        }
        result = store.append(
            event_id=event_id,
            occurred_at_ms=recorded_at_ms,
            event_type=cls.EVENT_TYPE,
            aggregate_id=bundle.bundle_id,
            payload=payload,
        )
        return cls._from_event(result.event), not result.duplicate

    @classmethod
    def _from_event(cls, event) -> HumanReviewAuthorization:
        p = event.payload
        return HumanReviewAuthorization(
            review_id=str(p["review_id"]),
            bundle_id=str(p["bundle_id"]),
            evidence_snapshot_id=str(p["evidence_snapshot_id"]),
            promotion_bundle_authorization_id=str(p["promotion_bundle_authorization_id"]),
            approval_id=str(p["approval_id"]),
            package_fingerprint=str(p["package_fingerprint"]),
            valid_from=datetime.fromisoformat(str(p["valid_from"])),
            expires_at=datetime.fromisoformat(str(p["expires_at"])),
            reviewers=tuple(str(x) for x in p["reviewers"]),
            recorded_at_ms=int(p["recorded_at_ms"]),
            dependency_checkpoint_sequence=int(p["dependency_checkpoint_sequence"]),
            dependency_keys=tuple(str(x) for x in p["dependency_keys"]),
        )

    def get(self, review_id: str) -> HumanReviewAuthorization | None:
        event = self.store.get(f"human-review:approve:{review_id}")
        return self._from_event(event) if event else None

    def assert_valid(
        self,
        review_id: str,
        *,
        bundle: PromotionBundle,
        approval: Approval,
        now: datetime,
        dependency_authority: DependencyInvalidationLedger,
    ) -> HumanReviewAuthorization:
        if now.tzinfo is None:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_TIMEZONE_REQUIRED")
        record = self.get(review_id)
        if record is None:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_NOT_FOUND")
        current = now.astimezone(timezone.utc)
        if current < record.valid_from or current >= record.expires_at:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_EXPIRED")
        if record.bundle_id != bundle.bundle_id or record.evidence_snapshot_id != bundle.evidence_snapshot_id:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_BUNDLE_MISMATCH")
        if record.approval_id != approval.approval_id:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_APPROVAL_MISMATCH")
        approval.validate(current)
        try:
            dependency_authority.assert_unchanged_since(record.dependency_checkpoint_sequence, record.dependency_keys)
        except DependencyInvalidationBlocked as exc:
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_STALE_AFTER_INVALIDATION") from exc
        if not self.store.verify_chain():
            raise HumanReviewAuthorityInvalid("HUMAN_REVIEW_EVENT_CHAIN_INVALID")
        return record

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError, EvidenceSnapshotAuthorityLedger


class CriticalPromotionEvidenceErrorV407(ValueError):
    __test__ = False


@dataclass(frozen=True)
class CriticalPromotionEvidenceDecisionV407:
    allowed: bool
    reason: str
    snapshot_id: str
    bundle_id: str


class CriticalPromotionEvidencePreflightV407:
    """Fail-closed preflight for the immutable Evidence Snapshot promotion boundary.

    This is deliberately read/verify-only. It does not create evidence, approvals,
    promotion bundles, or deployment state. The V3.98 critical-promotion authority
    calls the same underlying authority directly, making the preflight useful as an
    independent contract check without creating a bypass path.
    """

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.dependency_authority.store is not self.store:
            raise CriticalPromotionEvidenceErrorV407("SHARED_EVENT_STORE_REQUIRED")

    def check(self, *, bundle: PromotionBundle, now: datetime) -> CriticalPromotionEvidenceDecisionV407:
        try:
            if now.tzinfo is None:
                raise CriticalPromotionEvidenceErrorV407("NOW_TIMEZONE_REQUIRED")
            if not self.store.verify_chain():
                raise CriticalPromotionEvidenceErrorV407("EVENT_CHAIN_INVALID")
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
                dependency_authority=self.dependency_authority,
            )
            return CriticalPromotionEvidenceDecisionV407(True, "EVIDENCE_SNAPSHOT_FRESH_AND_BOUND", bundle.evidence_snapshot_id, bundle.bundle_id)
        except EvidenceSnapshotAuthorityError as exc:
            reason = str(exc)
            if reason == "EVIDENCE_SNAPSHOT_AUTHORITY_NOT_FOUND":
                reason = "EVIDENCE_SNAPSHOT_AUTHORITY_NOT_FOUND"
            return CriticalPromotionEvidenceDecisionV407(False, reason, bundle.evidence_snapshot_id, bundle.bundle_id)
        except CriticalPromotionEvidenceErrorV407 as exc:
            return CriticalPromotionEvidenceDecisionV407(False, str(exc), bundle.evidence_snapshot_id, bundle.bundle_id)

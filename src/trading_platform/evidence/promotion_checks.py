from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable
from datetime import datetime, timezone

if TYPE_CHECKING:
    from trading_platform.v329.dependency_authority import DependencyInvalidationLedger

@dataclass(frozen=True)
class PromotionPrerequisites:
    bundle_complete: bool
    compatibility_pass: bool
    evidence_valid: bool
    required_gates_pass: bool
    approval_valid: bool
    scope_valid: bool
    artifacts_integrity_valid: bool


def promotion_allowed(
    p: PromotionPrerequisites,
    *,
    dependency_authority: "DependencyInvalidationLedger",
    dependency_ids: Iterable[str],
    evidence_snapshot_id: str | None = None,
    promotion_id: str | None = None,
    bundle_id: str | None = None,
    model_version: str | None = None,
    now: datetime | None = None,
    promotion_bundle_authorization_id: str | None = None,
) -> bool:
    if dependency_authority is None:
        raise ValueError("DEPENDENCY_AUTHORITY_REQUIRED")
    if not all((evidence_snapshot_id, promotion_id, bundle_id, model_version, now, promotion_bundle_authorization_id)):
        return False
    try:
        dependency_authority.assert_clear(tuple(dependency_ids))
        from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger
        PromotionBundleAuthorityLedger(dependency_authority.store).assert_valid_binding(
            promotion_bundle_authorization_id, bundle_id=bundle_id, model_version=model_version,
            now=now, dependency_authority=dependency_authority,
        )
        from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
        EvidenceSnapshotAuthorityLedger(dependency_authority.store).assert_valid(
            evidence_snapshot_id, now=now, promotion_id=promotion_id, bundle_id=bundle_id,
            model_version=model_version, dependency_authority=dependency_authority,
        )
    except Exception as exc:
        from trading_platform.v329.dependency_authority import DependencyInvalidationError
        from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityError
        from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityError
        if isinstance(exc, (DependencyInvalidationError, EvidenceSnapshotAuthorityError, PromotionBundleAuthorityError)):
            return False
        raise
    return all((p.bundle_complete,p.compatibility_pass,p.evidence_valid,p.required_gates_pass,p.approval_valid,p.scope_valid,p.artifacts_integrity_valid))

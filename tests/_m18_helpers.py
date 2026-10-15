from datetime import datetime, timedelta, timezone

from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger


def evidence_snapshot_for(bundle, *, snapshot_id=None, scope=None, evidence_ids=('EV1',), metrics=None):
    snapshot_id = snapshot_id or bundle.evidence_snapshot_id
    metrics = metrics if metrics is not None else {"evidence_valid": True, "bundle_id": bundle.bundle_id}
    versions = (
        bundle.strategy_version, bundle.model_version, bundle.feature_version, bundle.target_version,
        bundle.configuration_version, bundle.execution_model_version, bundle.code_version,
    )
    hashes = tuple(bundle.artifact_hashes) + (bundle.content_hash,)
    dependencies = tuple(sorted(set((bundle.bundle_id, bundle.model_version, *bundle.gate_results, *evidence_ids))))
    return build_snapshot(
        snapshot_id,
        tuple(evidence_ids),
        metrics,
        tuple(bundle.gate_results),
        dependencies,
        versions,
        hashes,
        ("M18_EVIDENCE_METHOD",),
        (bundle.approval_id,),
        dict(bundle.scope if scope is None else scope),
    )


def authorize_evidence_snapshot(store, bundle, *, now=None, authorization_id=None, promotion_id=None,
                                model_version=None, snapshot_id=None, reviewer="reviewer", valid_for_hours=1):
    now = now or getattr(bundle, "created_at")
    snapshot = evidence_snapshot_for(bundle, snapshot_id=snapshot_id)
    dep = DependencyInvalidationLedger(store)
    ledger = EvidenceSnapshotAuthorityLedger(store)
    return ledger.authorize(
        snapshot=snapshot,
        promotion_id=promotion_id or bundle.bundle_id,
        bundle_id=bundle.bundle_id,
        model_version=model_version or bundle.model_version,
        valid_from=now - timedelta(days=1),
        expires_at=now + timedelta(hours=valid_for_hours),
        reviewer=reviewer,
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
        dependency_authority=dep,
    )[0]

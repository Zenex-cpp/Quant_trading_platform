from datetime import datetime, timedelta, timezone

from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
from trading_platform.v407.critical_promotion_evidence import CriticalPromotionEvidencePreflightV407

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)

def bundle() -> PromotionBundle:
    return PromotionBundle(
        "B407", "S407", "M407", "F407", "T407", "C407", "E407", "CODE407", "SNAP407",
        ("G407",), ("H407",), "APP407", {"environment": "PRODUCTION", "criticality": "CRITICAL"},
        "ROLLBACK407", "CONTENT407", NOW,
    )

def authorize(store, b, dep):
    snapshot = build_snapshot(
        b.evidence_snapshot_id, ("EV407",), {"metric": "verified"}, b.gate_results,
        (b.bundle_id,),
        (b.strategy_version, b.model_version, b.feature_version, b.target_version, b.configuration_version, b.execution_model_version, b.code_version),
        b.artifact_hashes, ("METHOD407",), (b.approval_id,), b.scope,
    )
    EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snapshot, promotion_id=b.bundle_id, bundle_id=b.bundle_id, model_version=b.model_version,
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        reviewer="snapshot-reviewer", recorded_at_ms=int(NOW.timestamp()*1000), dependency_authority=dep,
    )

def test_preflight_accepts_bound_fresh_snapshot():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = bundle(); authorize(store, b, dep)
    d = CriticalPromotionEvidencePreflightV407(store=store, dependency_authority=dep).check(bundle=b, now=NOW)
    assert d.allowed and d.reason == "EVIDENCE_SNAPSHOT_FRESH_AND_BOUND"

def test_preflight_rejects_missing_snapshot_authority():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = bundle()
    d = CriticalPromotionEvidencePreflightV407(store=store, dependency_authority=dep).check(bundle=b, now=NOW)
    assert not d.allowed and d.reason == "EVIDENCE_SNAPSHOT_AUTHORITY_NOT_FOUND"

def test_preflight_rejects_stale_snapshot_after_invalidation():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = bundle(); authorize(store, b, dep)
    graph_stub = type("Graph", (), {"version_hash": lambda self: "GRAPH",})()
    # Use a direct invalidation with no downstream graph impact on unrelated data,
    # but include the exact snapshot identity in the dependency set.
    from trading_platform.evidence.graph import EvidenceDependencyGraph
    graph = EvidenceDependencyGraph([])
    dep.invalidate(
        incident_id="INC407", changed_dependency=b.evidence_snapshot_id, graph=graph,
        evidence_index={}, gate_dependencies={}, candidates={}, promotions={},
        reason="SNAPSHOT_CHANGED", recorded_at_ms=int(NOW.timestamp()*1000)+1,
    )
    d = CriticalPromotionEvidencePreflightV407(store=store, dependency_authority=dep).check(bundle=b, now=NOW + timedelta(minutes=1))
    assert not d.allowed and d.reason == "EVIDENCE_SNAPSHOT_STALE_AFTER_INVALIDATION"

def test_preflight_rejects_bundle_mismatch():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = bundle(); authorize(store, b, dep)
    bad = PromotionBundle(**{**b.__dict__, "bundle_id": "OTHER"})
    d = CriticalPromotionEvidencePreflightV407(store=store, dependency_authority=dep).check(bundle=bad, now=NOW)
    assert not d.allowed and "PROMOTION_MISMATCH" in d.reason

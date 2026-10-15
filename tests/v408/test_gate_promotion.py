from datetime import datetime, timedelta, timezone

from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
from trading_platform.v408.gate_promotion import GatePromotionAuthorizationLedgerV408, CriticalPromotionGatePreflightV408
from trading_platform.evidence.graph import EvidenceDependencyGraph

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)

def make_bundle() -> PromotionBundle:
    return PromotionBundle(
        "B408", "S408", "M408", "F408", "T408", "C408", "E408", "CODE408", "SNAP408",
        ("G408",), ("H408",), "APP408", {"environment": "PRODUCTION", "criticality": "CRITICAL"},
        "ROLLBACK408", "CONTENT408", NOW,
    )

def make_gate() -> Gate:
    return Gate(
        "G408", "CAND408", "RUN408", ("M408",), ("CHECK408",), GateResult.PASS,
        ("H408",), ("EV408",), "owner", "reviewer", NOW.isoformat(), None, "rerun_on_dependency_change",
    )

def authorize_snapshot(store, bundle, dep):
    snapshot = build_snapshot(
        bundle.evidence_snapshot_id, ("EV408",), {"metric": "verified"}, bundle.gate_results,
        (bundle.bundle_id,),
        (bundle.strategy_version, bundle.model_version, bundle.feature_version, bundle.target_version,
         bundle.configuration_version, bundle.execution_model_version, bundle.code_version),
        bundle.artifact_hashes, ("METHOD408",), (bundle.approval_id,), bundle.scope,
    )
    EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snapshot, promotion_id=bundle.bundle_id, bundle_id=bundle.bundle_id, model_version=bundle.model_version,
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1),
        reviewer="snapshot-reviewer", recorded_at_ms=int(NOW.timestamp()*1000), dependency_authority=dep,
    )

def test_gate_authorization_is_required_and_then_reusable():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = make_bundle(); g = make_gate(); authorize_snapshot(store, b, dep)
    ledger = GatePromotionAuthorizationLedgerV408(store)
    try:
        ledger.assert_reusable(g, dep, int(NOW.timestamp()*1000))
        assert False
    except ValueError as exc:
        assert str(exc) == "GATE_PROMOTION_AUTHORIZATION_NOT_FOUND"
    ledger.authorize(gate=g, dependency_authority=dep, recorded_at_ms=int(NOW.timestamp()*1000))
    ledger.assert_reusable(g, dep, int(NOW.timestamp()*1000))

def test_strict_preflight_accepts_bound_gate_and_snapshot():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = make_bundle(); g = make_gate(); authorize_snapshot(store, b, dep)
    GatePromotionAuthorizationLedgerV408(store).authorize(gate=g, dependency_authority=dep, recorded_at_ms=int(NOW.timestamp()*1000))
    d = CriticalPromotionGatePreflightV408(store=store, dependency_authority=dep).check(bundle=b, gates=(g,), now=NOW)
    assert d.allowed

def test_strict_preflight_blocks_gate_after_invalidation():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = make_bundle(); g = make_gate(); authorize_snapshot(store, b, dep)
    GatePromotionAuthorizationLedgerV408(store).authorize(gate=g, dependency_authority=dep, recorded_at_ms=int(NOW.timestamp()*1000))
    graph = EvidenceDependencyGraph([])
    dep.invalidate(incident_id="INC408", changed_dependency="M408", graph=graph, evidence_index={}, gate_dependencies={}, candidates={}, promotions={}, reason="MODEL_CHANGED", recorded_at_ms=int(NOW.timestamp()*1000)+1)
    d = CriticalPromotionGatePreflightV408(store=store, dependency_authority=dep).check(bundle=b, gates=(g,), now=NOW + timedelta(minutes=1))
    assert not d.allowed and "GATE_REVALIDATION_REQUIRED:G408" in d.reason and "SNAPSHOT:EVIDENCE_SNAPSHOT_STALE_AFTER_INVALIDATION" in d.reason

def test_strict_preflight_rejects_missing_gate_object():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = make_bundle(); authorize_snapshot(store, b, dep)
    d = CriticalPromotionGatePreflightV408(store=store, dependency_authority=dep).check(bundle=b, gates=(), now=NOW)
    assert not d.allowed and d.reason == "GATE_OBJECT_MISSING:G408"

def test_gate_fingerprint_binding_blocks_mutation():
    store = EventStore(); dep = DependencyInvalidationLedger(store); b = make_bundle(); g = make_gate(); authorize_snapshot(store, b, dep)
    ledger = GatePromotionAuthorizationLedgerV408(store); ledger.authorize(gate=g, dependency_authority=dep, recorded_at_ms=int(NOW.timestamp()*1000))
    mutated = Gate(**{**g.__dict__, "checks": ("OTHER",)})
    try:
        ledger.assert_reusable(mutated, dep, int(NOW.timestamp()*1000))
        assert False
    except ValueError as exc:
        assert str(exc) == "GATE_AUTHORIZATION_FINGERPRINT_MISMATCH"

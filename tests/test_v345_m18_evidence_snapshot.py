from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.v21.event_store import EventStore
from trading_platform.v26.governance import ChampionChallengerRegistry, GovernedModel, GovernanceStatus
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger
from trading_platform.v345.evidence_snapshot_authority import (
    EvidenceSnapshotAuthorityConflict,
    EvidenceSnapshotAuthorityInvalid,
    EvidenceSnapshotAuthorityLedger,
)
from trading_platform.promotion.contracts import (
    Approval, DeploymentState, GateSummary, ModelRole, OperationalMode,
    PromotionBundle, ScopeCheck, promotion_allowed,
)
from trading_platform.v25.health import HealthState
from tests._m18_helpers import authorize_evidence_snapshot, evidence_snapshot_for
from tests._m19_helpers import authorize_promotion_bundle
from tests.v329.test_dependency_authority import graph, evidence_index

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def bundle():
    return PromotionBundle(
        "B-M18", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP-M18",
        ("G1",), ("hash1",), "A1", {"instrument": "BTCUSDT", "mode": "CANARY"},
        "RB1", "bundle-hash", NOW,
    )


def approval():
    return Approval("A1", ("reviewer",), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {})


def test_promotion_without_snapshot_is_blocked():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    assert not promotion_allowed(
        bundle=bundle(), gates=GateSummary(("G1",), ("G1",), ()), approval=approval(),
        evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True, "OK"),
        artifacts_integrity=True, now=NOW, dependency_authority=dep,
    )


def test_valid_immutable_snapshot_allows_promotion():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    bundle_auth = authorize_promotion_bundle(store, bundle(), now=NOW)
    assert promotion_allowed(
        bundle=bundle(), gates=GateSummary(("G1",), ("G1",), ()), approval=approval(),
        evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True, "OK"),
        artifacts_integrity=True, now=NOW, dependency_authority=dep, promotion_bundle_authorization_id=bundle_auth.authorization_id,
    )


def test_snapshot_persists_across_restart(tmp_path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    dep = DependencyInvalidationLedger(store)
    auth = authorize_evidence_snapshot(store, bundle(), now=NOW)
    restored = EvidenceSnapshotAuthorityLedger(EventStore(path)).get(auth.authorization_id)
    assert restored == auth


def test_tampered_snapshot_event_fails_closed(tmp_path):
    from tests._immutable_test_helpers import tamper_event_store
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', f"evidence-snapshot:authorize:{bundle().evidence_snapshot_id}"))
    dep = DependencyInvalidationLedger(store)
    assert not promotion_allowed(
        bundle=bundle(), gates=GateSummary(("G1",), ("G1",), ()), approval=approval(),
        evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True, "OK"),
        artifacts_integrity=True, now=NOW, dependency_authority=dep,
    )


def test_snapshot_binding_to_bundle_gate_artifact_and_scope_is_strict():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    b = bundle()
    authorize_evidence_snapshot(store, b, now=NOW)
    ledger = EvidenceSnapshotAuthorityLedger(store)
    with pytest.raises(EvidenceSnapshotAuthorityConflict, match="BUNDLE_MISMATCH"):
        ledger.assert_valid(b.evidence_snapshot_id, now=NOW, promotion_id=b.bundle_id, bundle_id="OTHER",
                            model_version=b.model_version, dependency_authority=dep)
    with pytest.raises(EvidenceSnapshotAuthorityConflict, match="SCOPE_MISMATCH"):
        ledger.assert_valid(b.evidence_snapshot_id, now=NOW, promotion_id=b.bundle_id, bundle_id=b.bundle_id,
                            model_version=b.model_version, requested_scope={"instrument": "ETHUSDT"}, dependency_authority=dep)
    with pytest.raises(EvidenceSnapshotAuthorityConflict, match="ARTIFACT_HASH_MISMATCH"):
        ledger.assert_valid(b.evidence_snapshot_id, now=NOW, promotion_id=b.bundle_id, bundle_id=b.bundle_id,
                            model_version=b.model_version, required_artifact_hashes=("other",), dependency_authority=dep)


def test_snapshot_is_stale_after_invalidating_change_even_after_revalidation():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    dep.invalidate(
        incident_id="INC-M18", changed_dependency="G1", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={}, reason="GATE_CHANGED", recorded_at_ms=2,
    )
    dep.revalidate(
        incident_id="INC-M18", revalidation_id="REV-M18", validation_fingerprint="FP",
        evidence_refs=("EV1",), gate_refs=("G1",), reviewer="reviewer", validated_at_ms=3,
    )
    with pytest.raises(EvidenceSnapshotAuthorityInvalid, match="STALE_AFTER_INVALIDATION"):
        EvidenceSnapshotAuthorityLedger(store).assert_valid(
            bundle().evidence_snapshot_id, now=NOW, promotion_id=bundle().bundle_id, bundle_id=bundle().bundle_id,
            model_version=bundle().model_version, required_gate_ids=bundle().gate_results,
            dependency_authority=dep,
        )


def test_champion_registry_requires_evidence_snapshot():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    gate, _ = ChampionGateAuthorityLedger.authorize(
        authorization_id="CA-M18", model_id="m2", model_version="1", candidate_id="m2",
        required_gate_ids=("G1",), passed_gate_ids=("G1",), promotion_id="P1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
        dependency_authority=dep, store=store,
    )
    model = GovernedModel("m2", "1", ModelRole.CHALLENGER, OperationalMode.SHADOW,
                          DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE,
                          True, True, Decimal("10"))
    current = GovernedModel("m1", "1", ModelRole.CHAMPION, OperationalMode.LIVE,
                            DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE,
                            True, True, Decimal("100"))
    with pytest.raises(ValueError, match="CHAMPION_GATE_EVIDENCE_AND_BUNDLE_AUTHORITY_REQUIRED"):
        ChampionChallengerRegistry((current, model)).promote(
            "m2", validated=True, gate_authorization=gate, dependency_authority=dep, now=NOW,
        )


def test_champion_registry_accepts_bound_evidence_snapshot():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    gate, _ = ChampionGateAuthorityLedger.authorize(
        authorization_id="CA-M18-2", model_id="m2", model_version="1", candidate_id="m2",
        required_gate_ids=("G1",), passed_gate_ids=("G1",), promotion_id="P1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
        dependency_authority=dep, store=store,
    )
    snapshot = build_snapshot("SNAP-P1", ("EV1",), {"candidate": "m2"}, ("G1",), ("P1", "m2"), ("1",), ("h",),
                               ("METHOD",), ("A1",), {"candidate": "m2"})
    snap_auth, _ = EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snapshot, promotion_id="P1", bundle_id="P1", model_version="1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=2,
        dependency_authority=dep,
    )
    promo_bundle = PromotionBundle("P1", "S", "1", "F", "T", "C", "E", "CODE", "SNAP", ("G1",), ("h",), "A1", {"candidate": "m2"}, "RB", "HASH", NOW)
    bundle_auth = authorize_promotion_bundle(store, promo_bundle, now=NOW, authorization_id="PB-M18")
    model = GovernedModel("m2", "1", ModelRole.CHALLENGER, OperationalMode.SHADOW,
                          DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE,
                          True, True, Decimal("10"))
    current = GovernedModel("m1", "1", ModelRole.CHAMPION, OperationalMode.LIVE,
                            DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE,
                            True, True, Decimal("100"))
    promoted = ChampionChallengerRegistry((current, model)).promote(
        "m2", validated=True, gate_authorization=gate, evidence_snapshot_authorization=snap_auth,
        promotion_bundle_authorization_id=bundle_auth.authorization_id, dependency_authority=dep, now=NOW,
    )
    assert promoted.champion().model_id == "m2"

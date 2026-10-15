from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v346.promotion_bundle_authority import (
    PromotionBundleAuthorityConflict,
    PromotionBundleAuthorityInvalid,
    PromotionBundleAuthorityLedger,
    promotion_bundle_fingerprint,
)
from trading_platform.promotion.contracts import Approval, GateSummary, PromotionBundle, ScopeCheck, promotion_allowed
from trading_platform.v26.governance import ChampionChallengerRegistry, GovernedModel, GovernanceStatus
from trading_platform.v25.health import HealthState
from trading_platform.promotion.contracts import DeploymentState, ModelRole, OperationalMode
from tests._m18_helpers import authorize_evidence_snapshot
from tests._m19_helpers import authorize_promotion_bundle
from tests.v329.test_dependency_authority import graph, evidence_index

NOW = datetime(2026, 9, 24, 16, 0, tzinfo=timezone.utc)


def bundle() -> PromotionBundle:
    return PromotionBundle(
        "B-M19", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1",
        ("G1",), ("hash1",), "A1", {"instrument": "BTCUSDT"}, "RB1", "HASH-M19", NOW,
    )


def approval() -> Approval:
    return Approval("A1", ("reviewer",), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {})


def test_authorization_binds_exact_bundle_fingerprint():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    auth, created = PromotionBundleAuthorityLedger.authorize(
        authorization_id="PB-M19", bundle=bundle(), valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
        dependency_authority=dep, store=store,
    )
    assert created
    assert auth.bundle_fingerprint == promotion_bundle_fingerprint(bundle())
    assert PromotionBundleAuthorityLedger(store).assert_valid(
        "PB-M19", bundle=bundle(), now=NOW, dependency_authority=dep
    ) == auth


def test_missing_bundle_authority_blocks_promotion():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    assert not promotion_allowed(
        bundle=bundle(), gates=GateSummary(("G1",), ("G1",), ()), approval=approval(),
        evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True, "OK"),
        artifacts_integrity=True, now=NOW, dependency_authority=dep,
    )


def test_changed_bundle_instance_is_blocked():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    auth = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M19-CHANGE")
    changed = PromotionBundle(
        "B-M19", "S1", "M1", "F1", "T1", "C1", "E1", "CODE2", "SNAP1",
        ("G1",), ("hash1",), "A1", {"instrument": "BTCUSDT"}, "RB1", "HASH-M19", NOW,
    )
    with pytest.raises(PromotionBundleAuthorityConflict, match="FINGERPRINT_MISMATCH"):
        PromotionBundleAuthorityLedger(store).assert_valid(
            auth.authorization_id, bundle=changed, now=NOW, dependency_authority=dep
        )


def test_authorization_survives_restart(tmp_path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    auth = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M19-RESTART")
    restored = PromotionBundleAuthorityLedger(EventStore(path)).get(auth.authorization_id)
    assert restored == auth


def test_tampered_authorization_event_fails_closed(tmp_path):
    from tests._immutable_test_helpers import tamper_event_store

    path = str(tmp_path / "events.db")
    store = EventStore(path)
    authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M19-TAMPER")
    tamper_event_store(
        store,
        "UPDATE events SET payload_json=? WHERE event_id=?",
        ("{}", "promotion-bundle:authorize:PB-M19-TAMPER"),
    )
    with pytest.raises(PromotionBundleAuthorityInvalid, match="EVENT_CHAIN"):
        PromotionBundleAuthorityLedger(store).get("PB-M19-TAMPER")


def test_invalidating_change_stales_bundle_even_after_revalidation():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    auth = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M19-STALE")
    dep.invalidate(
        incident_id="INC-M19", changed_dependency="G1", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={}, reason="GATE_CHANGED", recorded_at_ms=2,
    )
    dep.revalidate(
        incident_id="INC-M19", revalidation_id="REV-M19", validation_fingerprint="FP-M19",
        evidence_refs=("EV1",), gate_refs=("G1",), reviewer="reviewer", validated_at_ms=3,
    )
    with pytest.raises(PromotionBundleAuthorityInvalid, match="STALE_AFTER_INVALIDATION"):
        PromotionBundleAuthorityLedger(store).assert_valid(
            auth.authorization_id, bundle=bundle(), now=NOW, dependency_authority=dep
        )


def test_binding_path_also_blocks_stale_bundle():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    auth = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M19-BIND")
    dep.invalidate(
        incident_id="INC-M19-B", changed_dependency="CODE1", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={}, reason="CODE_CHANGED", recorded_at_ms=2,
    )
    with pytest.raises(PromotionBundleAuthorityInvalid, match="STALE_AFTER_INVALIDATION"):
        PromotionBundleAuthorityLedger(store).assert_valid_binding(
            auth.authorization_id, bundle_id=bundle().bundle_id, model_version=bundle().model_version,
            now=NOW, dependency_authority=dep,
        )


def test_champion_promotion_requires_bundle_authority_and_accepts_valid_binding():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger
    gate, _ = ChampionGateAuthorityLedger.authorize(
        authorization_id="CA-M19", model_id="M1", model_version="1", candidate_id="M1",
        required_gate_ids=("G1",), passed_gate_ids=("G1",), promotion_id=bundle().bundle_id,
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
        dependency_authority=dep, store=store,
    )
    from trading_platform.evidence.snapshot import build_snapshot
    snap = build_snapshot("SNAP-M19", ("EV1",), {"candidate": "M1"}, ("G1",), (bundle().bundle_id,), ("1",), ("hash1",), ("METHOD",), ("A1",), {"candidate": "M1"})
    snap_auth, _ = __import__("trading_platform.v345.evidence_snapshot_authority", fromlist=["EvidenceSnapshotAuthorityLedger"]).EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snap, promotion_id=bundle().bundle_id, bundle_id=bundle().bundle_id, model_version="1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=2,
        dependency_authority=dep,
    )
    c_auth = authorize_promotion_bundle(store, PromotionBundle(
        bundle().bundle_id, "S", "1", "F", "T", "C", "E", "CODE", "SNAP", ("G1",), ("hash1",),
        "A1", {"candidate": "M1"}, "RB", "HASH", NOW,
    ), now=NOW, authorization_id="PB-M19-CHAMP")
    challenger = GovernedModel("M1", "1", ModelRole.CHALLENGER, OperationalMode.SHADOW, DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE, True, True, Decimal("10"))
    current = GovernedModel("OLD", "1", ModelRole.CHAMPION, OperationalMode.LIVE, DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE, True, True, Decimal("100"))
    promoted = ChampionChallengerRegistry((current, challenger)).promote(
        "M1", validated=True, gate_authorization=gate, evidence_snapshot_authorization=snap_auth,
        promotion_bundle_authorization_id=c_auth.authorization_id, dependency_authority=dep, now=NOW,
    )
    assert promoted.champion().model_id == "M1"

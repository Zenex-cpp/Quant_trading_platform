from datetime import datetime, timedelta, timezone

import pytest

from tests._m14_helpers import authorize_compatibility, compatible_report
from tests._m15_helpers import authorize_artifact_integrity
from tests.v325.test_deployment_activation import bundle
from tests.v334_test_champion_authority import authority as champion_authority
from tests.v329.test_dependency_authority import graph, evidence_index
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger, ChampionGateAuthorityError
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityInvalid, CompatibilityAuthorityLedger
from trading_platform.v342.artifact_integrity import ArtifactIntegrityAuthorityInvalid, ArtifactIntegrityAuthorityLedger

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


def invalidate_and_revalidate(dep: DependencyInvalidationLedger, incident_id: str, dependency: str) -> None:
    dep.invalidate(
        incident_id=incident_id,
        changed_dependency=dependency,
        graph=graph(),
        evidence_index=evidence_index(),
        gate_dependencies={},
        candidates={},
        promotions={},
        reason="M17_INVALIDATING_CHANGE",
        recorded_at_ms=int((NOW + timedelta(seconds=2)).timestamp() * 1000),
    )
    dep.revalidate(
        incident_id=incident_id,
        revalidation_id=f"REV-{incident_id}",
        validation_fingerprint=f"validated:{incident_id}",
        evidence_refs=(f"E-{incident_id}",),
        gate_refs=(dependency,),
        reviewer="reviewer",
        validated_at_ms=int((NOW + timedelta(seconds=3)).timestamp() * 1000),
    )


def test_dependency_checkpoint_blocks_reuse_after_revalidated_change(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    dep = DependencyInvalidationLedger(store)
    checkpoint = dep.checkpoint()
    dep.invalidate(
        incident_id="INC-CHECKPOINT", changed_dependency="G1", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={}, reason="CHANGE", recorded_at_ms=2,
    )
    dep.revalidate(
        incident_id="INC-CHECKPOINT", revalidation_id="REV-CHECKPOINT", validation_fingerprint="fp",
        evidence_refs=("E1",), gate_refs=("G1",), reviewer="reviewer", validated_at_ms=3,
    )
    with pytest.raises(DependencyInvalidationBlocked, match="DEPENDENCY_INVALIDATION_AFTER_CHECKPOINT:G1"):
        dep.assert_unchanged_since(checkpoint, ("G1",))


def test_champion_gate_must_be_reissued_after_invalidating_change(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    auth, dep = champion_authority(store)
    invalidate_and_revalidate(dep, "INC-CHAMPION", "G1")
    with pytest.raises(ChampionGateAuthorityError, match="CHAMPION_GATE_STALE_AFTER_INVALIDATION"):
        ChampionGateAuthorityLedger(store).assert_valid(
            auth.authorization_id, now=NOW + timedelta(minutes=1), model_id="m2", model_version="1",
            candidate_id="m2", promotion_id="P1", dependency_authority=dep,
        )
    replacement, created = ChampionGateAuthorityLedger.authorize(
        authorization_id="CA2", model_id="m2", model_version="1", candidate_id="m2",
        required_gate_ids=("G1", "G2"), passed_gate_ids=("G1", "G2"), promotion_id="P1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=10,
        dependency_authority=dep, store=store,
    )
    assert created
    assert ChampionGateAuthorityLedger(store).assert_valid(
        replacement.authorization_id, now=NOW + timedelta(minutes=1), model_id="m2", model_version="1",
        candidate_id="m2", promotion_id="P1", dependency_authority=dep,
    ).authorization_id == "CA2"


def test_compatibility_gate_must_be_reissued_after_invalidating_change(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    dep = DependencyInvalidationLedger(store)
    b = bundle()
    auth = CompatibilityAuthorityLedger(store).authorize(
        authorization_id="COMPAT-M17-1", artifact_id=b.bundle_id, artifact_hashes=b.artifact_hashes,
        code_version=b.code_version, configuration_version=b.configuration_version,
        execution_model_version=b.execution_model_version, report=compatible_report(),
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        reviewer="reviewer", recorded_at_ms=1, dependency_authority=dep,
    )[0]
    invalidate_and_revalidate(dep, "INC-COMPAT", b.bundle_id)
    with pytest.raises(CompatibilityAuthorityInvalid, match="COMPATIBILITY_STALE_AFTER_INVALIDATION"):
        CompatibilityAuthorityLedger(store).assert_valid(
            auth.authorization_id, now=NOW + timedelta(minutes=1), artifact_id=b.bundle_id,
            artifact_hashes=b.artifact_hashes, code_version=b.code_version,
            configuration_version=b.configuration_version, execution_model_version=b.execution_model_version,
            dependency_authority=dep,
        )
    replacement = CompatibilityAuthorityLedger(store).authorize(
        authorization_id="COMPAT-M17-2", artifact_id=b.bundle_id, artifact_hashes=b.artifact_hashes,
        code_version=b.code_version, configuration_version=b.configuration_version,
        execution_model_version=b.execution_model_version, report=compatible_report(),
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        reviewer="reviewer", recorded_at_ms=10, dependency_authority=dep,
    )[0]
    assert replacement.authorization_id == "COMPAT-M17-2"


def test_integrity_gate_must_be_reissued_after_invalidating_change(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    dep = DependencyInvalidationLedger(store)
    b = bundle()
    auth = ArtifactIntegrityAuthorityLedger(store).authorize(
        authorization_id="INTEGRITY-M17-1", artifact_id=b.bundle_id, artifact_hashes=b.artifact_hashes,
        observed_artifact_hashes=b.artifact_hashes, manifest_hash="manifest-1", signature_verified=True,
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        reviewer="reviewer", recorded_at_ms=1, dependency_authority=dep,
    )[0]
    invalidate_and_revalidate(dep, "INC-INTEGRITY", b.bundle_id)
    with pytest.raises(ArtifactIntegrityAuthorityInvalid, match="ARTIFACT_INTEGRITY_STALE_AFTER_INVALIDATION"):
        ArtifactIntegrityAuthorityLedger(store).assert_valid(
            auth.authorization_id, now=NOW + timedelta(minutes=1), artifact_id=b.bundle_id,
            artifact_hashes=b.artifact_hashes, manifest_hash="manifest-1", dependency_authority=dep,
        )
    replacement = ArtifactIntegrityAuthorityLedger(store).authorize(
        authorization_id="INTEGRITY-M17-2", artifact_id=b.bundle_id, artifact_hashes=b.artifact_hashes,
        observed_artifact_hashes=b.artifact_hashes, manifest_hash="manifest-1", signature_verified=True,
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        reviewer="reviewer", recorded_at_ms=10, dependency_authority=dep,
    )[0]
    assert replacement.authorization_id == "INTEGRITY-M17-2"


def test_stale_gate_reuse_is_restart_persistent(tmp_path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    auth, dep = champion_authority(store)
    invalidate_and_revalidate(dep, "INC-RESTART", "G1")
    restarted = EventStore(path)
    with pytest.raises(ChampionGateAuthorityError, match="CHAMPION_GATE_STALE_AFTER_INVALIDATION"):
        ChampionGateAuthorityLedger(restarted).assert_valid(
            auth.authorization_id, now=NOW + timedelta(minutes=1), model_id="m2", model_version="1",
            candidate_id="m2", promotion_id="P1", dependency_authority=DependencyInvalidationLedger(restarted),
        )

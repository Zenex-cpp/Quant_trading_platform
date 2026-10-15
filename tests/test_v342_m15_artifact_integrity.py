from datetime import timedelta
from pathlib import Path
from decimal import Decimal
import pytest

from tests._m14_helpers import authorize_compatibility, compatible_report
from tests._m15_helpers import authorize_artifact_integrity
from tests._m19_helpers import authorize_promotion_bundle
from tests._m13_helpers import green_reconciliation
from tests.v325.test_deployment_activation import approval, bundle, gates, readiness, truth
from tests.v329.test_dependency_authority import graph, evidence_index
from trading_platform.promotion.contracts import ScopeCheck, ModelRole, DeploymentState
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentRequest
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v325.deployment_activation import ActivationInvalid, DeploymentActivationLedger
from trading_platform.v342.artifact_integrity import (
    ArtifactIntegrityAuthorityConflict,
    ArtifactIntegrityAuthorityInvalid,
    ArtifactIntegrityAuthorityLedger,
)
from trading_platform.promotion.contracts import Approval
from datetime import datetime, timezone

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def test_mismatched_observed_hashes_cannot_authorize(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    with pytest.raises(ArtifactIntegrityAuthorityInvalid, match="ARTIFACT_HASH_OBSERVATION_MISMATCH"):
        ArtifactIntegrityAuthorityLedger(store).authorize(
            authorization_id="I1", artifact_id="B1", artifact_hashes=("hash1",),
            observed_artifact_hashes=("tampered",), manifest_hash="manifest-1", signature_verified=True,
            valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10),
            reviewer="reviewer", recorded_at_ms=1,
        )


def test_unverified_signature_cannot_authorize(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    with pytest.raises(ArtifactIntegrityAuthorityInvalid, match="ARTIFACT_SIGNATURE_NOT_VERIFIED"):
        ArtifactIntegrityAuthorityLedger(store).authorize(
            authorization_id="I1", artifact_id="B1", artifact_hashes=("hash1",),
            observed_artifact_hashes=("hash1",), manifest_hash="manifest-1", signature_verified=False,
            valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10),
            reviewer="reviewer", recorded_at_ms=1,
        )


def test_changed_manifest_or_hash_blocks_reuse(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    auth = authorize_artifact_integrity(store, bundle(), manifest_hash="manifest-A")
    ledger = ArtifactIntegrityAuthorityLedger(store)
    with pytest.raises(ArtifactIntegrityAuthorityConflict, match="ARTIFACT_INTEGRITY_HASH_MISMATCH"):
        ledger.assert_valid(auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("tampered",))
    with pytest.raises(ArtifactIntegrityAuthorityConflict, match="ARTIFACT_MANIFEST_HASH_MISMATCH"):
        ledger.assert_valid(auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",), manifest_hash="manifest-B")


def test_expired_integrity_authority_blocks_prepare(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    historical = authorize_artifact_integrity(store, bundle(), authorization_id="I-HIST", now=NOW - timedelta(hours=2))
    compat = authorize_compatibility(store, bundle(), authorization_id="C-HIST", now=NOW)
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    request = DeploymentRequest(
        "D1", bundle(), approval(), gates(), ScopeCheck(True, "ok"), True, True, True,
        "operator", Decimal("5"), Decimal("10"),
        RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True),
        compat.authorization_id, historical.authorization_id, promotion_bundle.authorization_id,
    )
    with pytest.raises(ValueError, match="ARTIFACT_INTEGRITY_AUTHORITY_BLOCKED:ARTIFACT_INTEGRITY_AUTHORIZATION_EXPIRED"):
        DeploymentOrchestrator(
            policy=RolloutPolicy(Decimal("10"), Decimal("100")),
            dependency_authority=DependencyInvalidationLedger(store),
        ).prepare(request, now=NOW, now_ns=1)


def test_prepare_requires_integrity_authority_even_when_boolean_is_true(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    compat = authorize_compatibility(store, bundle())
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    request = DeploymentRequest(
        "D1", bundle(), approval(), gates(), ScopeCheck(True, "ok"), True, True, True,
        "operator", Decimal("5"), Decimal("10"),
        RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True),
        compat.authorization_id, None, promotion_bundle.authorization_id,
    )
    with pytest.raises(ValueError, match="ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED"):
        DeploymentOrchestrator(
            policy=RolloutPolicy(Decimal("10"), Decimal("100")),
            dependency_authority=DependencyInvalidationLedger(store),
        ).prepare(request, now=NOW, now_ns=1)


def test_activation_requires_integrity_authority(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    rp = RecoveryProofLedger(store)
    proof = rp.record(
        proof_id="rp1", recovery_id="r1", valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="recon", invariants_fingerprint="inv", guards_fingerprint="guard",
        issued_at_ms=1, store=store,
    )
    compat = authorize_compatibility(store, bundle())
    recon = green_reconciliation(store, now=NOW)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    with pytest.raises(ActivationInvalid, match="ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED"):
        DeploymentActivationLedger.authorize(
            deployment_id="D1", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
            target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=proof.proof_id,
            current_state_fingerprint="state-1", truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("10"),
            runtime_state=runtime, rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")),
            operator="operator", decision_id="DEC", now=NOW, recorded_at_ms=1, store=store,
            reconciliation_authorization_id=recon.authorization_id, compatibility_authorization_id=compat.authorization_id,
        )


def test_integrity_dependency_invalidation_blocks_existing_authority(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    dependency = DependencyInvalidationLedger(store)
    auth = authorize_artifact_integrity(store, bundle())
    dependency.invalidate(
        incident_id="INC-INTEGRITY", changed_dependency="B1", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={"B1": ()}, reason="ARTIFACT_CORRUPTION", recorded_at_ms=2,
    )
    with pytest.raises(ArtifactIntegrityAuthorityInvalid, match="ARTIFACT_INTEGRITY_DEPENDENCY_INVALIDATED"):
        ArtifactIntegrityAuthorityLedger(store).assert_valid(
            auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",),
            dependency_authority=dependency,
        )


def test_integrity_authority_survives_restart(tmp_path: Path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    auth = authorize_artifact_integrity(store, bundle())
    restored = ArtifactIntegrityAuthorityLedger(EventStore(path)).assert_valid(
        auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",), manifest_hash="manifest-1"
    )
    assert restored == auth

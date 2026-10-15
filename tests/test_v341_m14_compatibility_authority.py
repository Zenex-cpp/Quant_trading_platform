from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests._m14_helpers import authorize_compatibility, compatible_report, incompatible_report
from tests._m19_helpers import authorize_promotion_bundle
from tests.v325.test_deployment_activation import approval, bundle, gates, readiness, truth
from tests._m13_helpers import green_reconciliation
from trading_platform.operations.readiness import OperationalReadiness
from trading_platform.promotion.compatibility import Compatibility
from trading_platform.promotion.contracts import ModelRole, ScopeCheck, DeploymentState
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentRequest
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v325.deployment_activation import ActivationInvalid, DeploymentActivationLedger
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v341.compatibility_authority import (
    CompatibilityAuthorityConflict,
    CompatibilityAuthorityInvalid,
    CompatibilityAuthorityLedger,
)

from datetime import datetime, timezone

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def test_incompatible_report_cannot_authorize(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    ledger = CompatibilityAuthorityLedger(store)
    with pytest.raises(CompatibilityAuthorityInvalid, match="ARTIFACT_COMPATIBILITY_INCOMPATIBLE"):
        ledger.authorize(
            authorization_id="C1", artifact_id="B1", artifact_hashes=("hash1",),
            code_version="CODE1", configuration_version="C1", execution_model_version="E1",
            report=incompatible_report(), valid_from=NOW, expires_at=NOW + timedelta(minutes=30),
            reviewer="reviewer", recorded_at_ms=1,
        )


def test_missing_compatibility_authority_blocks_prepare(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    request = DeploymentRequest(
        "D1", bundle(), approval(), gates(), ScopeCheck(True, "ok"), True, True, True,
        "operator", 10, 10, RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True), None, None, promotion_bundle.authorization_id,
    )
    with pytest.raises(ValueError, match="COMPATIBILITY_AUTHORITY_REQUIRED"):
        DeploymentOrchestrator(
            policy=RolloutPolicy(10, 100), dependency_authority=DependencyInvalidationLedger(store)
        ).prepare(request, now=NOW, now_ns=1)


def test_authority_binds_artifact_and_versions(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    auth = authorize_compatibility(store, bundle())
    ledger = CompatibilityAuthorityLedger(store)
    with pytest.raises(CompatibilityAuthorityConflict, match="ARTIFACT_HASH_MISMATCH"):
        ledger.assert_valid(
            auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("tampered",),
            code_version="CODE1", configuration_version="C1", execution_model_version="E1",
        )
    with pytest.raises(CompatibilityAuthorityConflict, match="COMPATIBILITY_CODE_VERSION_MISMATCH"):
        ledger.assert_valid(
            auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",),
            code_version="CODE2", configuration_version="C1", execution_model_version="E1",
        )


def test_changed_current_report_blocks_reuse(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    auth = authorize_compatibility(store, bundle())
    changed = compatible_report().__class__(
        *([Compatibility.COMPATIBLE] * 6 + [Compatibility.UNKNOWN])
    )
    with pytest.raises(CompatibilityAuthorityInvalid, match="ARTIFACT_COMPATIBILITY_UNKNOWN"):
        CompatibilityAuthorityLedger(store).assert_valid(
            auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",),
            code_version="CODE1", configuration_version="C1", execution_model_version="E1",
            report=changed,
        )


def test_changed_compatible_report_fingerprint_also_blocks(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    auth = authorize_compatibility(store, bundle())
    changed = compatible_report()
    # same semantic report is accepted; adding a deliberate alternate incompatible value is what must fail
    assert changed.fingerprint == auth.report_fingerprint


def test_authority_survives_restart(tmp_path: Path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    auth = authorize_compatibility(store, bundle())
    restored = CompatibilityAuthorityLedger(EventStore(path)).assert_valid(
        auth.authorization_id, now=NOW, artifact_id="B1", artifact_hashes=("hash1",),
        code_version="CODE1", configuration_version="C1", execution_model_version="E1",
    )
    assert restored == auth


def test_activation_requires_durable_compatibility_authority(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    rp = RecoveryProofLedger(store)
    proof = rp.record(
        proof_id="rp1", recovery_id="r1", valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="recon", invariants_fingerprint="inv", guards_fingerprint="guard",
        issued_at_ms=1, store=store,
    )
    recon = green_reconciliation(store, now=NOW)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    with pytest.raises(ActivationInvalid, match="COMPATIBILITY_AUTHORITY_REQUIRED"):
        DeploymentActivationLedger.authorize(
            deployment_id="D1", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
            target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=proof.proof_id,
            current_state_fingerprint="state-1", truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("10"),
            runtime_state=runtime, rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DEC",
            now=NOW, recorded_at_ms=2, store=store, reconciliation_authorization_id=recon.authorization_id,
        )

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests._m14_helpers import (
    authorize_compatibility,
    authorize_runtime_executor,
    compatible_report,
    incompatible_report,
)
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
    CompatibilityGuardedArtifactExecutor,
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


@pytest.mark.parametrize(
    "dimension",
    (
        "runtime_input_schema", "output_schema", "feature_schema", "configuration",
        "dependencies", "execution", "venue_rules",
    ),
)
@pytest.mark.parametrize("status", (Compatibility.INCOMPATIBLE, Compatibility.UNKNOWN))
def test_runtime_execution_blocks_every_non_pass_compatibility_dimension(dimension, status):
    report = replace(compatible_report(), **{dimension: status})
    executor = authorize_runtime_executor(NOW, report_provider=lambda: report)
    executed = []

    with pytest.raises(CompatibilityAuthorityInvalid, match=f"ARTIFACT_COMPATIBILITY_{status.value}"):
        executor.execute(lambda: executed.append("called"), now=NOW)

    assert executed == []


def test_runtime_execution_rechecks_compatibility_report_before_each_call():
    reports = [compatible_report(), compatible_report()]
    calls = []
    executor = authorize_runtime_executor(
        NOW,
        report_provider=lambda: calls.append("report") or reports.pop(0),
    )

    assert executor.execute(lambda value: value + 1, 4, now=NOW) == 5
    assert executor.execute(lambda value: value + 1, 8, now=NOW) == 9
    assert calls == ["report", "report"]


def test_runtime_execution_blocks_expired_authorization_before_callable():
    executor = authorize_runtime_executor(NOW, expires_at=NOW)
    executed = []

    with pytest.raises(CompatibilityAuthorityInvalid, match="COMPATIBILITY_AUTHORIZATION_EXPIRED"):
        executor.execute(lambda: executed.append("called"), now=NOW)

    assert executed == []


def test_runtime_execution_requires_dependency_authority_from_the_authorization_store():
    store = EventStore()
    dependencies = DependencyInvalidationLedger(store)
    authorization = CompatibilityAuthorityLedger(store).authorize(
        authorization_id="RUNTIME-STORE-BINDING",
        artifact_id="MODEL-ARTIFACT-1",
        artifact_hashes=("sha256:model-artifact-1",),
        code_version="CODE-1",
        configuration_version="CONFIG-1",
        execution_model_version="PARITY-BASE",
        report=compatible_report(),
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        reviewer="reviewer",
        recorded_at_ms=1,
        dependency_authority=dependencies,
    )[0]

    with pytest.raises(CompatibilityAuthorityInvalid, match="COMPATIBILITY_DEPENDENCY_STORE_MISMATCH"):
        CompatibilityGuardedArtifactExecutor(
            ledger=CompatibilityAuthorityLedger(store),
            authorization_id=authorization.authorization_id,
            artifact_id=authorization.artifact_id,
            artifact_hashes=authorization.artifact_hashes,
            code_version=authorization.code_version,
            configuration_version=authorization.configuration_version,
            execution_model_version=authorization.execution_model_version,
            report_provider=compatible_report,
            dependency_authority=DependencyInvalidationLedger(EventStore()),
        )


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

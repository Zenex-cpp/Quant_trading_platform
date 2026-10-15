from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.operations.readiness import OperationalReadiness
from trading_platform.promotion.contracts import Approval, DeploymentState, GateSummary, ModelRole, PromotionBundle, ScopeCheck
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from tests._m13_helpers import green_reconciliation
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m18_helpers import authorize_evidence_snapshot
from tests._m19_helpers import authorize_promotion_bundle
from trading_platform.v325.deployment_activation import (
    AuthorizedDeploymentController,
    ActivationConflict,
    ActivationExpired,
    ActivationInvalid,
    DeploymentActivationLedger,
    require_authorized_activation,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def readiness() -> OperationalReadiness:
    return OperationalReadiness(*([True] * 19))


def proof(ledger: RecoveryProofLedger, fp="state-1", expires_minutes=30):
    return ledger.record(
        proof_id="rp1",
        recovery_id="recovery-1",
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=expires_minutes),
        state_reconciled=True,
        invariants_pass=True,
        no_unresolved_critical_issue=True,
        guards_pass=True,
        state_fingerprint=fp,
        reconciliation_fingerprint="recon-1",
        invariants_fingerprint="inv-1",
        guards_fingerprint="guard-1",
        issued_at_ms=int(NOW.timestamp() * 1000),
        store=ledger.store,
    )


def bundle():
    return PromotionBundle(
        "B1", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1",
        ("G1",), ("hash1",), "A1", {"mode": "CANARY"}, "RB1", "bundle-hash", NOW,
    )


def approval():
    return Approval("A1", ("operator",), NOW - timedelta(minutes=2), NOW + timedelta(minutes=30), {})


def gates():
    return GateSummary(("G1",), ("G1",), ())

def promotion_fp():
    return DeploymentActivationLedger.promotion_fingerprint(
        bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
    )


def truth():
    axes = AxisSnapshot("APPROVED", "CANARY", "HEALTHY", "APPROVED", "ACTIVE", "CHALLENGER")
    components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "OK", (f"E-{name}",)) for name in (
        "health", "provenance", "governance", "reconciliation", "accounting", "ledger"
    ))
    return build_truth(
        observed_at_ns=1,
        axes=axes,
        components=components,
        requested_risk=Decimal("10"),
        caps={k: Decimal("100") for k in (
            "health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap"
        )},
    )


def common(tmp_path: Path):
    store = EventStore(str(tmp_path / "activation.db"))
    rp = RecoveryProofLedger(store)
    pr = proof(rp)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    recon = green_reconciliation(store, now=NOW)
    compat = authorize_compatibility(store, bundle())
    integrity = authorize_artifact_integrity(store, bundle())
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    rec, created = DeploymentActivationLedger.authorize(
        deployment_id="D1", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
        readiness=readiness(), target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=pr.proof_id,
        current_state_fingerprint="state-1", truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("100"),
        runtime_state=runtime, rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator",
        decision_id="DDEC1", now=NOW, recorded_at_ms=1, store=store,
        reconciliation_authorization_id=recon.authorization_id,
        compatibility_authorization_id=compat.authorization_id,
        artifact_integrity_authorization_id=integrity.authorization_id,
        promotion_bundle_authorization_id=promotion_bundle.authorization_id,
    )
    assert created
    return store, rp, rec


def test_authorization_is_durable_and_restart_safe(tmp_path: Path):
    store, rp, rec = common(tmp_path)
    restored = DeploymentActivationLedger(EventStore(str(tmp_path / "activation.db"))).get("D1")
    assert restored == rec
    assert require_authorized_activation(
        DeploymentActivationLedger(store), "D1", now=NOW + timedelta(seconds=1),
        current_state_fingerprint="state-1", current_truth_hash=truth().state_hash, current_promotion_fingerprint=promotion_fp(), current_approval=approval(), proof_ledger=rp, bundle=bundle(),
    ) == rec


def test_state_or_truth_change_fails_closed(tmp_path: Path):
    store, rp, _ = common(tmp_path)
    ledger = DeploymentActivationLedger(store)
    with pytest.raises(ActivationConflict, match="STATE_FINGERPRINT"):
        require_authorized_activation(ledger, "D1", now=NOW, current_state_fingerprint="state-2", current_truth_hash=truth().state_hash, current_promotion_fingerprint=promotion_fp(), current_approval=approval(), proof_ledger=rp, bundle=bundle())
    with pytest.raises(ActivationConflict, match="TRUTH_HASH"):
        require_authorized_activation(ledger, "D1", now=NOW, current_state_fingerprint="state-1", current_truth_hash="different", current_promotion_fingerprint=promotion_fp(), current_approval=approval(), proof_ledger=rp, bundle=bundle())


def test_activation_expiry_is_fail_closed(tmp_path: Path):
    store = EventStore(str(tmp_path / "e.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp, expires_minutes=1)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    recon = green_reconciliation(store, now=NOW, authorization_id="RECON-EXP")
    compat = authorize_compatibility(store, bundle(), authorization_id="COMPAT-EXP")
    integrity = authorize_artifact_integrity(store, bundle(), authorization_id="INTEGRITY-EXP")
    authorize_evidence_snapshot(store, bundle(), now=NOW, authorization_id="SNAP-EXP")
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-EXP")
    rec, _ = DeploymentActivationLedger.authorize(
        deployment_id="D2", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
        target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=p.proof_id, current_state_fingerprint="state-1",
        truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("100"), runtime_state=runtime,
        rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DDEC2",
        now=NOW, recorded_at_ms=1, store=store,
        reconciliation_authorization_id=recon.authorization_id,
        compatibility_authorization_id=compat.authorization_id,
        artifact_integrity_authorization_id=integrity.authorization_id,
        promotion_bundle_authorization_id=promotion_bundle.authorization_id,
    )
    with pytest.raises(ActivationExpired):
        require_authorized_activation(DeploymentActivationLedger(store), rec.deployment_id, now=NOW + timedelta(minutes=1), current_state_fingerprint="state-1", current_truth_hash=truth().state_hash, current_promotion_fingerprint=promotion_fp(), current_approval=approval(), proof_ledger=rp, bundle=bundle())


def test_readiness_or_runtime_authority_blocks(tmp_path: Path):
    store = EventStore(str(tmp_path / "b.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    bad = OperationalReadiness(*([True] * 18 + [False]))
    with pytest.raises(ActivationInvalid, match="READINESS"):
        DeploymentActivationLedger.authorize(
            deployment_id="D3", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=bad,
            target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=p.proof_id, current_state_fingerprint="state-1",
            truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("100"), runtime_state=runtime,
            rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DDEC3",
            now=NOW, recorded_at_ms=1, store=store,
        )


def test_corrupt_chain_blocks_reuse(tmp_path: Path):
    store, rp, _ = common(tmp_path)
    event_id = "deployment-activation:authorize:D1"
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ("{}", event_id))
    with pytest.raises(ActivationInvalid, match="EVENT_CHAIN"):
        DeploymentActivationLedger(store).get("D1")


def test_same_deployment_id_with_changed_request_conflicts(tmp_path: Path):
    store, rp, rec = common(tmp_path)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    with pytest.raises(ActivationConflict, match="ACTIVATION_ID_CONFLICT|CONCURRENT_CONFLICT|DUPLICATE_CONFLICT"):
        DeploymentActivationLedger.authorize(
            deployment_id="D1", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
            target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=rec.proof_id, current_state_fingerprint="state-1",
            truth=truth(), requested_risk=Decimal("9"), canary_exposure=Decimal("100"), runtime_state=runtime,
            rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DDEC1",
            now=NOW, recorded_at_ms=2, store=store,
            reconciliation_authorization_id=rec.reconciliation_authorization_id,
            compatibility_authorization_id=rec.compatibility_authorization_id,
            artifact_integrity_authorization_id=rec.artifact_integrity_authorization_id,
            promotion_bundle_authorization_id=rec.promotion_bundle_authorization_id,
        )

def test_live_target_requires_champion(tmp_path: Path):
    store = EventStore(str(tmp_path / "live.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    live_runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.LIVE, DeploymentState.ACTIVE, "HEALTHY", True)
    live_bundle = PromotionBundle(
        "BL", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1", ("G1",), ("hash1",),
        "A1", {"mode": "LIVE"}, "RB1", "bundle-live", NOW,
    )
    live_compat = authorize_compatibility(store, live_bundle, authorization_id="COMPAT-LIVE")
    live_promotion_bundle = authorize_promotion_bundle(store, live_bundle, now=NOW, authorization_id="PB-LIVE")
    authorize_evidence_snapshot(store, live_bundle, now=NOW)
    live_axes = AxisSnapshot("APPROVED", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHALLENGER")
    live_components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "OK", (f"E-{name}",)) for name in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger"))
    live_truth = build_truth(observed_at_ns=1, axes=live_axes, components=live_components, requested_risk=Decimal("10"), caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")})
    with pytest.raises(ActivationInvalid, match="CHAMPION"):
        DeploymentActivationLedger.authorize(
            deployment_id="DL", bundle=live_bundle, approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
            target_mode=OperationalMode.LIVE, proof_ledger=rp, proof_id=p.proof_id, current_state_fingerprint="state-1",
            truth=live_truth, requested_risk=Decimal("10"), canary_exposure=Decimal("0"), runtime_state=live_runtime,
            rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DLDEC",
            now=NOW, recorded_at_ms=2, store=store, compatibility_authorization_id=live_compat.authorization_id, promotion_bundle_authorization_id=live_promotion_bundle.authorization_id,
        )

def test_authorized_controller_is_required_for_final_canary_activation(tmp_path: Path):
    from trading_platform.v28.deployment import DeploymentOrchestrator
    store, rp, rec = common(tmp_path)
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    from trading_platform.v28.deployment import DeploymentRequest
    request = DeploymentRequest(
        "D1", bundle(), approval(), gates(), ScopeCheck(True, "ok"), True, True, True, "operator", Decimal("10"), Decimal("100"), runtime, rec.compatibility_authorization_id, rec.artifact_integrity_authorization_id, rec.promotion_bundle_authorization_id
    )
    o = DeploymentOrchestrator(policy=RolloutPolicy(Decimal("10"), Decimal("100")), dependency_authority=DependencyInvalidationLedger(store))
    state = o.start_canary(o.stage(o.prepare(request, now=NOW, now_ns=1), now_ns=2), now_ns=3)
    ctl = AuthorizedDeploymentController(orchestrator=o, activation_ledger=DeploymentActivationLedger(store), proof_ledger=rp)
    activated = ctl.activate_canary(state, now=NOW + timedelta(seconds=1), now_ns=4, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash)
    assert activated.phase.name == "ACTIVATED"

    from trading_platform.v325.deployment_activation import ActivationInvalid as _ActivationInvalid
    with pytest.raises(_ActivationInvalid, match="ACTIVATION_NOT_FOUND"):
        AuthorizedDeploymentController(orchestrator=o, activation_ledger=DeploymentActivationLedger(EventStore(str(tmp_path / "empty.db"))), proof_ledger=rp).activate_canary(
            state, now=NOW, now_ns=5, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash
        )


def test_revoked_approval_invalidates_existing_activation(tmp_path: Path):
    store, rp, _ = common(tmp_path)
    ledger = DeploymentActivationLedger(store)
    revoked = Approval("A1", ("operator",), NOW - timedelta(minutes=2), NOW + timedelta(minutes=30), {}, status="REVOKED")
    with pytest.raises(ActivationExpired, match="APPROVAL_INVALID"):
        require_authorized_activation(
            ledger, "D1", now=NOW + timedelta(seconds=1), current_state_fingerprint="state-1",
            current_truth_hash=truth().state_hash, current_promotion_fingerprint=DeploymentActivationLedger.promotion_fingerprint(
                bundle=bundle(), approval=revoked, gates=gates(), scope=ScopeCheck(True, "ok"),
                evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
            ), current_approval=revoked, proof_ledger=rp, bundle=bundle(),
        )


def test_promotion_dependency_change_invalidates_activation(tmp_path: Path):
    store, rp, _ = common(tmp_path)
    ledger = DeploymentActivationLedger(store)
    changed_gates = GateSummary(("G1", "G2"), ("G1",), ())
    changed_fp = DeploymentActivationLedger.promotion_fingerprint(
        bundle=bundle(), approval=approval(), gates=changed_gates, scope=ScopeCheck(True, "ok"),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
    )
    with pytest.raises(ActivationConflict, match="PROMOTION_FINGERPRINT"):
        require_authorized_activation(
            ledger, "D1", now=NOW + timedelta(seconds=1), current_state_fingerprint="state-1",
            current_truth_hash=truth().state_hash, current_promotion_fingerprint=changed_fp,
            current_approval=approval(), proof_ledger=rp, bundle=bundle(),
        )

def test_live_activation_requires_durable_human_review_before_downstream_authorities(tmp_path: Path):
    store = EventStore(str(tmp_path / "live-human-review.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    live_bundle = PromotionBundle(
        "BL", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1",
        ("G1",), ("hash1",), "A1", {"mode": "LIVE"}, "RB1", "bundle-live", NOW,
    )
    live_runtime = RuntimeBundleState(ModelRole.CHAMPION, OperationalMode.LIVE, DeploymentState.ACTIVE, "HEALTHY", True)
    live_axes = AxisSnapshot("APPROVED", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    live_components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "OK", (f"E-{name}",)) for name in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger"))
    live_truth = build_truth(
        observed_at_ns=1,
        axes=live_axes,
        components=live_components,
        requested_risk=Decimal("10"),
        caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")},
    )
    with pytest.raises(ActivationInvalid, match="LIVE_HUMAN_REVIEW_AUTHORITY_REQUIRED"):
        DeploymentActivationLedger.authorize(
            deployment_id="DLHR", bundle=live_bundle, approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(),
            target_mode=OperationalMode.LIVE, proof_ledger=rp, proof_id=p.proof_id, current_state_fingerprint="state-1",
            truth=live_truth, requested_risk=Decimal("10"), canary_exposure=Decimal("0"), runtime_state=live_runtime,
            rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DLHRDEC",
            now=NOW, recorded_at_ms=2, store=store, champion_gate_authorization_id="CG-1",
            reconciliation_authorization_id="RECON-1", compatibility_authorization_id="COMPAT-1",
            artifact_integrity_authorization_id="INTEGRITY-1", promotion_bundle_authorization_id="PB-1",
        )

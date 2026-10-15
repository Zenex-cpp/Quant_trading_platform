from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.promotion.contracts import Approval, DeploymentState, GateSummary, ModelRole, PromotionBundle, ScopeCheck
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from tests._m13_helpers import green_reconciliation
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m19_helpers import authorize_promotion_bundle
from tests._m18_helpers import authorize_evidence_snapshot
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentRequest
from trading_platform.v28.deployment_authority import ActivationCapabilityError
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v325.deployment_activation import DeploymentActivationLedger, AuthorizedDeploymentController
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v326.transition_authority import (
    DeploymentStateTransitionAuthority,
    StateTransitionAuthorityConflict,
    StateTransitionAuthorityInvalid,
    StateTransitionAuthorityLedger,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def readiness():
    from trading_platform.operations.readiness import OperationalReadiness
    return OperationalReadiness(*([True] * 19))


def bundle():
    return PromotionBundle("B1", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1", ("G1",), ("hash1",), "A1", {"mode": "CANARY"}, "RB1", "bundle-hash", NOW)


def approval():
    return Approval("A1", ("operator",), NOW - timedelta(minutes=2), NOW + timedelta(minutes=30), {})


def gates():
    return GateSummary(("G1",), ("G1",), ())


def truth():
    axes = AxisSnapshot("APPROVED", "CANARY", "HEALTHY", "APPROVED", "ACTIVE", "CHALLENGER")
    components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "OK", (f"E-{name}",)) for name in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger"))
    return build_truth(observed_at_ns=1, axes=axes, components=components, requested_risk=Decimal("10"), caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")})


def promotion_fp():
    return DeploymentActivationLedger.promotion_fingerprint(bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"), evidence_valid=True, compatibility_valid=True, artifacts_integrity=True)


def build_authorized(tmp_path: Path):
    store = EventStore(str(tmp_path / "ledger.db"))
    proof_ledger = RecoveryProofLedger(store)
    proof = proof_ledger.record(
        proof_id="rp1", recovery_id="recovery-1", valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="recon-1", invariants_fingerprint="inv-1", guards_fingerprint="guard-1",
        issued_at_ms=1000, store=store,
    )
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    recon = green_reconciliation(store, now=NOW)
    compat = authorize_compatibility(store, bundle())
    integrity = authorize_artifact_integrity(store, bundle())
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    activation, _ = DeploymentActivationLedger.authorize(
        deployment_id="D1", bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, "ok"),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(), target_mode=OperationalMode.CANARY,
        proof_ledger=proof_ledger, proof_id=proof.proof_id, current_state_fingerprint="state-1", truth=truth(),
        requested_risk=Decimal("10"), canary_exposure=Decimal("100"), runtime_state=runtime,
        rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DDEC1",
        now=NOW, recorded_at_ms=2000, store=store, reconciliation_authorization_id=recon.authorization_id,
        compatibility_authorization_id=compat.authorization_id,
        artifact_integrity_authorization_id=integrity.authorization_id,
        promotion_bundle_authorization_id=promotion_bundle.authorization_id,
    )
    request = DeploymentRequest("D1", bundle(), approval(), gates(), ScopeCheck(True, "ok"), True, True, True, "operator", Decimal("10"), Decimal("100"), runtime, compat.authorization_id, integrity.authorization_id, promotion_bundle.authorization_id)
    orch = DeploymentOrchestrator(policy=RolloutPolicy(Decimal("10"), Decimal("100")), dependency_authority=DependencyInvalidationLedger(store))
    state = orch.start_canary(orch.stage(orch.prepare(request, now=NOW, now_ns=1), now_ns=2), now_ns=3)
    authority = DeploymentStateTransitionAuthority(
        activation_ledger=DeploymentActivationLedger(store), proof_ledger=proof_ledger,
        transition_ledger=StateTransitionAuthorityLedger(store),
    )
    return store, proof_ledger, activation, state, orch, authority


def test_legacy_v28_activate_is_blocked_without_capability(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    with pytest.raises(ActivationCapabilityError, match="AUTHORITY_REQUIRED"):
        orch.activate(state, now=NOW, now_ns=4)


def test_final_transition_requires_durable_v326_authority(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    result = authority.activate(
        state, now=NOW + timedelta(seconds=1), now_ns=4,
        current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator="operator", decision_id="TDEC1", transition_id="T1", orchestrator=orch,
    )
    assert result.phase is DeploymentPhase.ACTIVATED
    assert result.allocated_risk <= Decimal("10")
    rec = StateTransitionAuthorityLedger(store).get("T1")
    assert rec is not None and rec.status.name == "AUTHORIZED"


def test_transition_authorization_survives_restart(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    rec = authority.authorize_final_activation(
        state, now=NOW, now_ns=4, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(), operator="operator", decision_id="TDEC2", transition_id="T2",
    )
    restored = StateTransitionAuthorityLedger(EventStore(str(tmp_path / "ledger.db"))).get("T2")
    assert restored == rec


def test_changed_activation_fingerprint_conflicts(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    authority.authorize_final_activation(
        state, now=NOW, now_ns=4, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(), operator="operator", decision_id="TDEC3", transition_id="T3",
    )
    with pytest.raises(StateTransitionAuthorityConflict, match="TRANSITION_ID_CONFLICT"):
        authority.transition_ledger.authorize(
            authority.transition_ledger._from_payload({
                **authority.transition_ledger.payload_from_record(authority.transition_ledger.get("T3")),
                "truth_hash": "changed",
            })
        )


def test_state_change_blocks_final_transition(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    from trading_platform.v325.deployment_activation import ActivationConflict
    with pytest.raises(ActivationConflict, match="STATE_FINGERPRINT"):
        authority.activate(
            state, now=NOW, now_ns=4, current_state_fingerprint="state-2", current_truth_hash=truth().state_hash,
            current_promotion_fingerprint=promotion_fp(), current_approval=approval(), operator="operator", decision_id="TDEC4", transition_id="T4", orchestrator=orch,
        )


def test_transition_audit_corruption_blocks_use(tmp_path: Path):
    store, proof_ledger, activation, state, orch, authority = build_authorized(tmp_path)
    authority.authorize_final_activation(
        state, now=NOW, now_ns=4, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(), operator="operator", decision_id="TDEC5", transition_id="T5",
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ("{}", "deployment-transition:authorize:T5"))
    with pytest.raises(StateTransitionAuthorityInvalid, match="EVENT_CHAIN"):
        authority.transition_ledger.get("T5")

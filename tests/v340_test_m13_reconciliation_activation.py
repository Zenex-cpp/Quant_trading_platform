from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests._m13_helpers import green_reconciliation, red_reconciliation
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m19_helpers import authorize_promotion_bundle
from tests._m18_helpers import authorize_evidence_snapshot
from trading_platform.operations.readiness import OperationalReadiness
from trading_platform.promotion.contracts import Approval, DeploymentState, GateSummary, ModelRole, PromotionBundle, ScopeCheck
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from trading_platform.v20.reconciliation import ReconciliationState, RestWebSocketReconciler
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v325.deployment_activation import ActivationInvalid, DeploymentActivationLedger, require_authorized_activation
from trading_platform.v340.reconciliation_authority import ReconciliationAuthorityError, ReconciliationAuthorityLedger
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def readiness():
    return OperationalReadiness(*([True] * 19))


def approval():
    return Approval("A1", ("operator",), NOW - timedelta(minutes=2), NOW + timedelta(minutes=30), {})


def bundle():
    return PromotionBundle(
        "B1", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1",
        ("G1",), ("hash1",), "A1", {"mode": "CANARY"}, "RB1", "bundle-hash", NOW,
    )


def truth():
    axes = AxisSnapshot("APPROVED", "CANARY", "HEALTHY", "APPROVED", "ACTIVE", "CHALLENGER")
    components = tuple(TruthComponent(name, TruthStatus.VERIFIED, "OK") for name in (
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


def proof(store):
    return RecoveryProofLedger(store).record(
        proof_id="rp1", recovery_id="r1",
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="recon-green", invariants_fingerprint="inv", guards_fingerprint="guard",
        issued_at_ms=1, store=store,
    )


def authorize(store, recon_id: str):
    rp = RecoveryProofLedger(store)
    p = proof(store)
    compat = authorize_compatibility(store, bundle())
    integrity = authorize_artifact_integrity(store, bundle())
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW, authorization_id="PB-M13")
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    return DeploymentActivationLedger.authorize(
        deployment_id="D1", bundle=bundle(), approval=approval(), gates=GateSummary(("G1",), ("G1",), ()),
        scope=ScopeCheck(True, "ok"), evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
        readiness=readiness(), target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=p.proof_id,
        current_state_fingerprint="state-1", truth=truth(), requested_risk=Decimal("10"), canary_exposure=Decimal("100"),
        runtime_state=RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True),
        rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DEC1",
        now=NOW, recorded_at_ms=10, store=store, reconciliation_authorization_id=recon_id, compatibility_authorization_id=compat.authorization_id, artifact_integrity_authorization_id=integrity.authorization_id, promotion_bundle_authorization_id=promotion_bundle.authorization_id,
    )


def test_activation_requires_durable_reconciliation_authority(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    with pytest.raises(ActivationInvalid, match="RECONCILIATION_BLOCKED:RECONCILIATION_AUTHORIZATION_NOT_FOUND"):
        authorize(store, "MISSING")


def test_green_reconciliation_authorizes_activation(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    recon = green_reconciliation(store, now=NOW)
    rec, created = authorize(store, recon.authorization_id)
    assert created
    assert rec.reconciliation_authorization_id == recon.authorization_id


def test_critical_mismatch_after_green_invalidates_activation(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    green = green_reconciliation(store, now=NOW)
    rec, _ = authorize(store, green.authorization_id)
    red = red_reconciliation(store, now=NOW, authorization_id="RECON-RED-AFTER")
    assert red.critical
    with pytest.raises(ActivationInvalid, match="RECONCILIATION_BLOCKED:RECONCILIATION_AUTHORIZATION_SUPERSEDED"):
        require_authorized_activation(
            DeploymentActivationLedger(store), "D1", now=NOW + timedelta(seconds=1),
            current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
            current_promotion_fingerprint=DeploymentActivationLedger.promotion_fingerprint(
                bundle=bundle(), approval=approval(), gates=GateSummary(("G1",), ("G1",), ()),
                scope=ScopeCheck(True, "ok"), evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
            ), current_approval=approval(), proof_ledger=RecoveryProofLedger(store),
        )


def test_current_hash_mismatch_blocks_activation(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    green = green_reconciliation(store, now=NOW, rest_hash="REST-1", stream_hash="STREAM-1")
    ReconciliationAuthorityLedger(store).assert_activation_safe(
        green.authorization_id, now=NOW, scope_id="PRODUCTION", current_rest_hash="REST-1", current_stream_hash="STREAM-1"
    )
    with pytest.raises(ReconciliationAuthorityError, match="RECONCILIATION_REST_HASH_MISMATCH"):
        ReconciliationAuthorityLedger(store).assert_activation_safe(
            green.authorization_id, now=NOW, scope_id="PRODUCTION", current_rest_hash="REST-2"
        )


def test_real_rest_stream_mismatch_blocks_activation_authority(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    result = RestWebSocketReconciler().reconcile(
        rest_account={"openOrders": [{"orderId": "O1", "status": "FILLED", "executedQty": "1"}]},
        stream_account={"openOrders": [{"orderId": "O1", "status": "FILLED", "executedQty": "2"}]},
    )
    assert result.state is ReconciliationState.RED
    rec, _ = ReconciliationAuthorityLedger(store).record_result(
        authorization_id="RECON-REAL-RED", scope_id="PRODUCTION", case_id="CASE-REAL-RED", result=result,
        valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30), observed_at_ms=int(NOW.timestamp() * 1000),
        operator="reconciler",
    )
    assert rec.critical
    with pytest.raises(ActivationInvalid, match="RECONCILIATION_BLOCKED:RECONCILIATION_CRITICAL_MISMATCH"):
        authorize(store, rec.authorization_id)


def test_restart_preserves_latest_reconciliation_authority(tmp_path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    green = green_reconciliation(store, now=NOW)
    red_reconciliation(store, now=NOW, authorization_id="RECON-RED-RESTART")
    restarted = ReconciliationAuthorityLedger(EventStore(path))
    with pytest.raises(ReconciliationAuthorityError, match="RECONCILIATION_AUTHORIZATION_SUPERSEDED"):
        restarted.assert_activation_safe(green.authorization_id, now=NOW, scope_id="PRODUCTION")


def test_new_green_observation_reopens_authority(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    green_reconciliation(store, now=NOW, authorization_id="RECON-1")
    red_reconciliation(store, now=NOW, authorization_id="RECON-2")
    new_green = green_reconciliation(store, now=NOW, authorization_id="RECON-3")
    restored = ReconciliationAuthorityLedger(store).assert_activation_safe(new_green.authorization_id, now=NOW, scope_id="PRODUCTION")
    assert restored.authorization_id == "RECON-3"

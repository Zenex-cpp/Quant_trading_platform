from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger, ChampionGateAuthorityError
from trading_platform.v26.governance import ChampionChallengerRegistry, GovernedModel, GovernanceStatus
from tests._m14_helpers import authorize_compatibility
from trading_platform.v25.health import HealthState
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)

def challenger():
    return GovernedModel("m2", "1", ModelRole.CHALLENGER, OperationalMode.SHADOW, DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE, True, True, Decimal("10"))

def champion():
    return GovernedModel("m1", "1", ModelRole.CHAMPION, OperationalMode.LIVE, DeploymentState.ACTIVE, HealthState.HEALTHY, GovernanceStatus.ELIGIBLE, True, True, Decimal("100"))

def authority(store):
    dep = DependencyInvalidationLedger(store)
    rec, created = ChampionGateAuthorityLedger.authorize(
        authorization_id="CA1", model_id="m2", model_version="1", candidate_id="m2",
        required_gate_ids=("G1", "G2"), passed_gate_ids=("G1", "G2"), promotion_id="P1",
        valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
        dependency_authority=dep, store=store,
    )
    assert created
    return rec, dep

def test_no_champion_promotion_without_gate_authority():
    with pytest.raises(ValueError, match="CHAMPION_GATE_EVIDENCE_AND_BUNDLE_AUTHORITY_REQUIRED"):
        ChampionChallengerRegistry((champion(), challenger())).promote("m2", validated=True)

def test_champion_promotion_requires_all_gates(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    dep = DependencyInvalidationLedger(store)
    with pytest.raises(ChampionGateAuthorityError, match="REQUIRED_GATES_NOT_PASSED"):
        ChampionGateAuthorityLedger.authorize(
            authorization_id="CA1", model_id="m2", model_version="1", candidate_id="m2",
            required_gate_ids=("G1", "G2"), passed_gate_ids=("G1",), promotion_id="P1",
            valid_from=NOW, expires_at=NOW + timedelta(hours=1), reviewer="reviewer", recorded_at_ms=1,
            dependency_authority=dep, store=store,
        )

def test_champion_promotion_requires_evidence_snapshot_and_bundle_authority(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    auth, dep = authority(store)
    with pytest.raises(ValueError, match="CHAMPION_GATE_EVIDENCE_AND_BUNDLE_AUTHORITY_REQUIRED"):
        ChampionChallengerRegistry((champion(), challenger())).promote(
            "m2", validated=True, gate_authorization=auth, dependency_authority=dep,
            now=NOW + timedelta(seconds=1),
        )

def test_invalidated_gate_blocks_champion_authority(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    auth, dep = authority(store)
    # A direct dependency invalidation is sufficient to revoke usability of the durable authorization.
    dep.invalidate(
        incident_id="INC-G1", changed_dependency="G1", graph=__import__('trading_platform.evidence.graph', fromlist=['EvidenceDependencyGraph']).EvidenceDependencyGraph(),
        evidence_index={}, gate_dependencies={}, candidates={}, promotions={}, reason="GATE_INVALIDATED", recorded_at_ms=2,
    )
    with pytest.raises(ChampionGateAuthorityError, match="CHAMPION_GATE_DEPENDENCY_BLOCKED"):
        ChampionGateAuthorityLedger(store).assert_valid("CA1", now=NOW + timedelta(seconds=1), model_id="m2", model_version="1", candidate_id="m2", promotion_id="P1", dependency_authority=dep)

def test_authority_survives_restart(tmp_path):
    path = str(tmp_path / "events.db")
    store = EventStore(path)
    auth, dep = authority(store)
    restored = ChampionGateAuthorityLedger(EventStore(path)).assert_valid("CA1", now=NOW + timedelta(seconds=1), model_id="m2", model_version="1", candidate_id="m2", promotion_id="P1", dependency_authority=DependencyInvalidationLedger(EventStore(path)))
    assert restored.fingerprint == auth.fingerprint

def test_live_activation_requires_durable_champion_gate_authority(tmp_path):
    from trading_platform.operations.readiness import OperationalReadiness
    from trading_platform.promotion.contracts import Approval, GateSummary, PromotionBundle, ScopeCheck
    from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
    from trading_platform.state.enums import OperationalMode
    from trading_platform.v324.recovery_proof import RecoveryProofLedger
    from trading_platform.v325.deployment_activation import DeploymentActivationLedger, ActivationInvalid
    from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
    store = EventStore(str(tmp_path / "live.db"))
    rp = RecoveryProofLedger(store)
    proof = rp.record(proof_id="rp1", recovery_id="r1", valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30), state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True, state_fingerprint="state-1", reconciliation_fingerprint="recon", invariants_fingerprint="inv", guards_fingerprint="guard", issued_at_ms=1, store=store)
    b = PromotionBundle("BL","S1","M1","F1","T1","C1","E1","CODE1","SNAP1",("G1",),("hash1",),"A1",{"mode":"LIVE"},"RB1","h",NOW)
    approval = Approval("A1", ("operator",), NOW - timedelta(minutes=1), NOW + timedelta(minutes=30), {})
    gates = __import__('trading_platform.promotion.contracts', fromlist=['GateSummary']).GateSummary(("G1",),("G1",),())
    axes = AxisSnapshot("APPROVED","LIVE","HEALTHY","APPROVED","ACTIVE","CHAMPION")
    comps = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    truth = build_truth(observed_at_ns=1, axes=axes, components=comps, requested_risk=Decimal("10"), caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})
    runtime = RuntimeBundleState(ModelRole.CHAMPION, OperationalMode.LIVE, DeploymentState.ACTIVE, "HEALTHY", True)
    compat = authorize_compatibility(store, b, authorization_id="COMPAT-LIVE")
    with pytest.raises(ActivationInvalid, match="LIVE_CHAMPION_GATE_AUTHORITY_REQUIRED"):
        DeploymentActivationLedger.authorize(
            deployment_id="DL", bundle=b, approval=approval, gates=gates, scope=ScopeCheck(True,"ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=OperationalReadiness(*([True]*19)),
            target_mode=OperationalMode.LIVE, proof_ledger=rp, proof_id=proof.proof_id, current_state_fingerprint="state-1",
            truth=truth, requested_risk=Decimal("10"), canary_exposure=Decimal("0"), runtime_state=runtime,
            rollout_policy=RolloutPolicy(Decimal("10"),Decimal("100")), operator="operator", decision_id="D", now=NOW, recorded_at_ms=2, store=store, compatibility_authorization_id=compat.authorization_id,
        )

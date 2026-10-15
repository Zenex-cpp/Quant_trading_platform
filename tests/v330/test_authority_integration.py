from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph, EvidenceState
from trading_platform.data.holdout import HoldoutPolicy, Workflow, HoldoutAccessContext, HoldoutAccessContextRequired
from trading_platform.promotion.contracts import GateSummary, PromotionBundle, Approval, ScopeCheck, promotion_allowed, DeploymentState, ModelRole, OperationalMode
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.evidence.promotion_checks import PromotionPrerequisites, promotion_allowed as legacy_promotion_allowed
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentRequest, DeploymentPhase
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m18_helpers import authorize_evidence_snapshot
from tests._m19_helpers import authorize_promotion_bundle

NOW=datetime(2026,9,23,10,0,tzinfo=timezone.utc)

def bundle():
    return PromotionBundle('B1','S1','M1','F1','T1','C1','E1','CODE1','SNAP1',('G1',),('H1',),'A1',{},'RB','HASH',NOW)

def auth_for(*, holdout='H1', store):
    return HoldoutAccessContext.build(
        store=store, graph=EvidenceDependencyGraph(),
        evidence_index={'EV1': Evidence('EV1','RESEARCH',EvidenceState.VALID,'1',NOW.isoformat(),(holdout,),(holdout,), 'm',{},(None,None),'h','research')},
        gate_dependencies={'G1': ('EV1',)}, candidates={'C1': ('G1',)}, promotions={'B1': ('C1',)},
    )

def test_gate_summary_requires_dependency_authority():
    with pytest.raises(TypeError):
        GateSummary(('G1',),('G1',),()).all_required_passed()

def test_promotion_rejects_missing_dependency_authority():
    a=Approval('A1',('reviewer',),NOW-timedelta(minutes=1),NOW+timedelta(hours=1),{})
    with pytest.raises(TypeError):
        promotion_allowed(bundle=bundle(), gates=GateSummary(('G1',),('G1',),()), approval=a, evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True,'ok'), artifacts_integrity=True, now=NOW)

def test_promotion_is_blocked_by_active_invalidation():
    store=EventStore()
    ledger=DependencyInvalidationLedger(store)
    ctx=auth_for(store=store)
    bundle_auth=authorize_promotion_bundle(store,bundle(),now=NOW)
    ledger.invalidate(incident_id='INC-H', changed_dependency='H1', graph=ctx.graph, evidence_index=ctx.evidence_index, gate_dependencies=ctx.gate_dependencies, candidates=ctx.candidates, promotions=ctx.promotions, reason='HOLDOUT_CONTAMINATION', recorded_at_ms=1)
    a=Approval('A1',('reviewer',),NOW-timedelta(minutes=1),NOW+timedelta(hours=1),{})
    assert not promotion_allowed(bundle=bundle(), gates=GateSummary(('G1',),('G1',),()), approval=a, evidence_valid=True, compatibility_valid=True, scope=ScopeCheck(True,'ok'), artifacts_integrity=True, now=NOW, dependency_authority=ledger, promotion_bundle_authorization_id=bundle_auth.authorization_id)

def test_forbidden_holdout_access_emits_violation_and_invalidates_dependents():
    store=EventStore()
    ctx=auth_for(store=store)
    policy=HoldoutPolicy('H1')
    with pytest.raises(PermissionError, match='FINAL_HOLDOUT_ACCESS_FORBIDDEN'):
        policy.authorize(Workflow.TUNING, context=ctx, access_id='ACCESS-1', actor='research-agent', attempted_at_ms=2)
    assert store.get('holdout-access:ACCESS-1') is not None
    assert store.get('holdout-violation:ACCESS-1') is not None
    with pytest.raises(DependencyInvalidationBlocked):
        ctx.dependency_ledger.assert_clear(('H1','EV1','G1','C1','B1'))

def test_allowed_final_evaluation_is_logged():
    store=EventStore(); ctx=auth_for(store=store); policy=HoldoutPolicy('H1')
    policy.authorize(Workflow.FINAL_EVALUATION, context=ctx, access_id='ACCESS-2', actor='validator', attempted_at_ms=3)
    rec=policy.audit_record(context=ctx, access_id='ACCESS-2')
    assert rec is not None and rec.allowed is True and rec.workflow is Workflow.FINAL_EVALUATION

def test_holdout_access_without_context_fails_closed():
    with pytest.raises(HoldoutAccessContextRequired, match='HOLDOUT_ACCESS_CONTEXT_REQUIRED'):
        HoldoutPolicy('H1').authorize(Workflow.TUNING, context=None, access_id='A', actor='research', attempted_at_ms=1)

def test_holdout_violation_survives_restart():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path=d+'/events.db'
        s=EventStore(path); ctx=auth_for(store=s); HoldoutPolicy('H1')
        with pytest.raises(PermissionError):
            HoldoutPolicy('H1').authorize(Workflow.TUNING, context=ctx, access_id='ACCESS-3', actor='research', attempted_at_ms=4)
        restored=EventStore(path); ledger=DependencyInvalidationLedger(restored)
        with pytest.raises(DependencyInvalidationBlocked): ledger.assert_clear(('H1','EV1','G1','C1','B1'))


def deployment_request(store=None, authorize_snapshot=True):
    approval=Approval("A1",("operator",),NOW-timedelta(minutes=1),NOW+timedelta(hours=1),{})
    bundle_obj=bundle()
    runtime=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.CANARY,DeploymentState.ACTIVE,"HEALTHY",True)
    compat_id = authorize_compatibility(store, bundle_obj, now=NOW).authorization_id if store is not None else None
    integrity_id = authorize_artifact_integrity(store, bundle_obj, now=NOW).authorization_id if store is not None else None
    promotion_bundle = authorize_promotion_bundle(store, bundle_obj, now=NOW) if store is not None else None
    if store is not None and authorize_snapshot:
        authorize_evidence_snapshot(store, bundle_obj, now=NOW)
    return DeploymentRequest("D1",bundle_obj,approval,GateSummary(("G1",),("G1",),()),ScopeCheck(True,"ok"),True,True,True,"operator",Decimal("5"),Decimal("10"),runtime,compat_id,integrity_id,(promotion_bundle.authorization_id if promotion_bundle else None))

def test_deployment_orchestrator_requires_explicit_dependency_authority():
    with pytest.raises(TypeError):
        DeploymentOrchestrator(policy=RolloutPolicy(Decimal("10"),Decimal("100")))

def test_deployment_prepare_consumes_shared_dependency_authority():
    store=EventStore(); ledger=DependencyInvalidationLedger(store); ctx=auth_for(store=store)
    request = deployment_request(store, authorize_snapshot=False)
    ledger.invalidate(incident_id="INC-GATE", changed_dependency="G1", graph=ctx.graph, evidence_index=ctx.evidence_index, gate_dependencies={}, candidates={}, promotions={}, reason="GATE_INVALIDATED", recorded_at_ms=5)
    orch=DeploymentOrchestrator(policy=RolloutPolicy(Decimal("10"),Decimal("100")), dependency_authority=ledger)
    with pytest.raises(ValueError, match="DEPLOYMENT_GATE_BLOCKED"):
        orch.prepare(request, now=NOW, now_ns=1)


def test_legacy_promotion_check_requires_dependency_authority_and_blocks_invalidated_dependency():
    p=PromotionPrerequisites(True,True,True,True,True,True,True)
    with pytest.raises(TypeError):
        legacy_promotion_allowed(p, dependency_ids=("B1",))
    store=EventStore(); ledger=DependencyInvalidationLedger(store)
    ctx=auth_for(store=store)
    bundle_auth=authorize_promotion_bundle(store,bundle(),now=NOW)
    ledger.invalidate(incident_id="INC-LEGACY", changed_dependency="B1", graph=ctx.graph, evidence_index=ctx.evidence_index, gate_dependencies=ctx.gate_dependencies, candidates=ctx.candidates, promotions=ctx.promotions, reason="INVALIDATION", recorded_at_ms=6)
    assert legacy_promotion_allowed(p, dependency_authority=ledger, dependency_ids=("B1",), evidence_snapshot_id="SNAP1", promotion_id="B1", bundle_id="B1", model_version="M1", now=NOW, promotion_bundle_authorization_id=bundle_auth.authorization_id) is False


def test_legacy_promotion_check_requires_promotion_bundle_authority():
    p=PromotionPrerequisites(True,True,True,True,True,True,True)
    store=EventStore(); ledger=DependencyInvalidationLedger(store)
    assert legacy_promotion_allowed(p, dependency_authority=ledger, dependency_ids=("B1",), evidence_snapshot_id="SNAP1", promotion_id="B1", bundle_id="B1", model_version="M1", now=NOW) is False

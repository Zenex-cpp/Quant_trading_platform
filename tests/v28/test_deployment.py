from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from trading_platform.promotion.contracts import PromotionBundle, Approval, GateSummary, ScopeCheck
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState
from trading_platform.v28.deployment import DeploymentRequest, DeploymentOrchestrator, DeploymentPhase
from trading_platform.v28.deployment_authority import activation_capability_context, _issue_activation_capability
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from tests._m19_helpers import authorize_promotion_bundle
from trading_platform.v21.event_store import EventStore
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m18_helpers import authorize_evidence_snapshot

NOW=datetime.now(timezone.utc)

def req(store, risk="10", exposure="50"):
    bundle=PromotionBundle('B1','S1','M1','F1','T1','C1','E1','CODE1','SNAP1',('G1',),('h1',),'A1',{'mode':'CANARY'},'RB1','h',NOW)
    approval=Approval('A1',('operator',),NOW-timedelta(minutes=1),NOW+timedelta(hours=1),{})
    runtime=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.CANARY,DeploymentState.ACTIVE,'HEALTHY',True)
    compat = authorize_compatibility(store, bundle, now=NOW)
    integrity = authorize_artifact_integrity(store, bundle, now=NOW)
    promotion_bundle = authorize_promotion_bundle(store, bundle, now=NOW)
    authorize_evidence_snapshot(store, bundle, now=NOW)
    return DeploymentRequest('D1',bundle,approval,GateSummary(('G1',),('G1',),()),ScopeCheck(True,'ok'),True,True,True,'operator',Decimal(risk),Decimal(exposure),runtime,compat.authorization_id,integrity.authorization_id,promotion_bundle.authorization_id)

def orch(store): return DeploymentOrchestrator(policy=RolloutPolicy(Decimal('10'),Decimal('100'),True,True), dependency_authority=DependencyInvalidationLedger(store))


def authorize_for_unit_test(state):
    return _issue_activation_capability(
        deployment_id=state.request.deployment_id,
        activation_fingerprint="UNIT_TEST_AUTHORITY",
        target_mode=state.request.runtime_state.mode.value,
        effective_risk=state.allocated_risk,
        valid_from=NOW-timedelta(minutes=1),
        expires_at=NOW+timedelta(minutes=30),
    )

def test_prepare_stage_canary_activate():
    store=EventStore(); o=orch(store); s=o.prepare(req(store),now=NOW,now_ns=1); assert s.phase is DeploymentPhase.PREPARED and not s.trading_allowed
    s=o.stage(s,now_ns=2); s=o.start_canary(s,now_ns=3); assert s.phase is DeploymentPhase.CANARY and s.allocated_risk==Decimal('10')
    with activation_capability_context(authorize_for_unit_test(s)):
        s=o.activate(s,now=NOW,now_ns=4); assert s.phase is DeploymentPhase.ACTIVATED and s.trading_allowed

def test_gate_failure_is_fail_closed():
    store=EventStore(); base=req(store); r=DeploymentRequest(base.deployment_id,base.bundle,base.approval,GateSummary(('G1',),(),()),base.scope,True,True,True,base.operator,base.requested_risk,base.canary_exposure,base.runtime_state,base.compatibility_authorization_id,base.artifact_integrity_authorization_id,base.promotion_bundle_authorization_id)
    with pytest.raises(ValueError,match='DEPLOYMENT_GATE_BLOCKED'): orch(store).prepare(r,now=NOW,now_ns=1)

def test_canary_cannot_exceed_cap():
    store=EventStore()
    with pytest.raises(ValueError,match='CANARY_RISK_CAP_BREACH'):
        o=orch(store); s=o.prepare(req(store,'11'),now=NOW,now_ns=1); s=o.stage(s,now_ns=2); o.start_canary(s,now_ns=3)

def test_abort_zeroes_risk():
    store=EventStore(); o=orch(store); s=o.prepare(req(store),now=NOW,now_ns=1); s=o.stage(s,now_ns=2); s=o.start_canary(s,now_ns=3); s=o.abort(s,reason='health degraded',now_ns=4)
    assert s.phase is DeploymentPhase.ABORTED and s.allocated_risk==Decimal('0') and not s.trading_allowed

def test_rollback_zeroes_risk_and_close():
    store=EventStore(); o=orch(store); s=o.prepare(req(store),now=NOW,now_ns=1); s=o.stage(s,now_ns=2); s=o.start_canary(s,now_ns=3)
    with activation_capability_context(authorize_for_unit_test(s)):
        s=o.activate(s,now=NOW,now_ns=4)
    s=o.rollback(s,reason='drift critical',now_ns=5)
    assert s.phase is DeploymentPhase.ROLLED_BACK and s.allocated_risk==0 and not s.trading_allowed
    s=o.close(s,now_ns=6); assert s.phase is DeploymentPhase.CLOSED

def test_activation_requires_fresh_approval():
    store=EventStore(); o=orch(store); r=req(store); a=Approval('A1',('operator',),NOW-timedelta(hours=2),NOW-timedelta(hours=1),{})
    historical_compat = authorize_compatibility(store, r.bundle, authorization_id='COMPAT-HIST', now=NOW-timedelta(hours=2))
    historical_integrity = authorize_artifact_integrity(store, r.bundle, authorization_id='INTEGRITY-HIST', now=NOW-timedelta(hours=2))
    historical_bundle = authorize_promotion_bundle(store, r.bundle, authorization_id='PB-HIST', now=NOW-timedelta(hours=2))
    r=DeploymentRequest(r.deployment_id,r.bundle,a,r.gates,r.scope,r.evidence_valid,r.compatibility_valid,r.artifacts_integrity,r.operator,r.requested_risk,r.canary_exposure,r.runtime_state,historical_compat.authorization_id,historical_integrity.authorization_id,historical_bundle.authorization_id)
    s=o.prepare(r,now=NOW-timedelta(hours=2),now_ns=1); s=o.stage(s,now_ns=2); s=o.start_canary(s,now_ns=3)
    with activation_capability_context(authorize_for_unit_test(s)):
        with pytest.raises(ValueError): o.activate(s,now=NOW,now_ns=4)

def test_unhealthy_activation_blocked():
    store=EventStore(); o=orch(store); r=req(store); rt=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.CANARY,DeploymentState.ACTIVE,'FROZEN',True)
    r=DeploymentRequest(r.deployment_id,r.bundle,r.approval,r.gates,r.scope,r.evidence_valid,r.compatibility_valid,r.artifacts_integrity,r.operator,r.requested_risk,r.canary_exposure,rt,r.compatibility_authorization_id,r.artifact_integrity_authorization_id,r.promotion_bundle_authorization_id)
    with pytest.raises(ValueError,match='UNHEALTHY_BUNDLE_BLOCKED'):
        st=o.start_canary(o.stage(o.prepare(r,now=NOW,now_ns=1),now_ns=2),now_ns=3)
        with activation_capability_context(authorize_for_unit_test(st)):
            o.activate(st,now=NOW,now_ns=4)

def test_audit_chain_detects_tampering():
    store=EventStore(); o=orch(store); s=o.prepare(req(store),now=NOW,now_ns=1); s=o.stage(s,now_ns=2); s.chain.verify(); e=s.chain.events[0]; bad=e.__class__(e.sequence,e.event_type,e.deployment_id,e.actor,e.from_phase,e.to_phase,e.risk_before,Decimal('9'),e.reason,e.timestamp_ns,e.previous_hash,e.event_hash)
    from trading_platform.v28.deployment import DeploymentAuditChain
    with pytest.raises(ValueError,match='DEPLOYMENT_CHAIN_INVALID'): DeploymentAuditChain((bad,)).verify()

def test_terminal_close_rejects_active():
    store=EventStore(); o=orch(store); s=o.prepare(req(store),now=NOW,now_ns=1)
    with pytest.raises(ValueError,match='CLOSE_REQUIRES_TERMINAL_PHASE'): o.close(s,now_ns=2)

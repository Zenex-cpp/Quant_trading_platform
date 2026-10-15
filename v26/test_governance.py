from decimal import Decimal
from datetime import datetime, timedelta, timezone
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger
from trading_platform.v25.health import HealthAssessment, HealthState
from trading_platform.v26.governance import *
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState

def h(state=HealthState.HEALTHY, drift=False, reason="HEALTHY"): return HealthAssessment(state,True,drift,True,reason,"a1")
def m(role=ModelRole.CHAMPION, mode=OperationalMode.LIVE, hs=HealthState.HEALTHY): return GovernedModel("m1","1",role,mode,DeploymentState.ACTIVE,hs,GovernanceStatus.ELIGIBLE,True,True,Decimal("100"))
def e(valid=True, reason=""): return EvidenceValidity("m1",valid,reason,10)
NOW=datetime(2026,9,23,tzinfo=timezone.utc)
def gate_ctx(candidate="m2"):
    store=EventStore()
    dep=DependencyInvalidationLedger(store)
    auth,_=ChampionGateAuthorityLedger.authorize(authorization_id="CA1",model_id=candidate,model_version="1",candidate_id=candidate,required_gate_ids=("G1",),passed_gate_ids=("G1",),promotion_id="P1",valid_from=NOW,expires_at=NOW+timedelta(hours=1),reviewer="reviewer",recorded_at_ms=1,dependency_authority=dep,store=store)
    return auth,dep

def test_healthy(): assert evaluate_model(model=m(),health=h(),evidence=e(),approved_risk_budget=Decimal("100")).effective_risk_budget==100
def test_degraded_demotes(): 
    d=evaluate_model(model=m(),health=h(HealthState.DEGRADED,reason="DATA_QUALITY_DEGRADED"),evidence=e(),approved_risk_budget=Decimal("100"))
    assert d.status is GovernanceStatus.DEMOTED and d.effective_risk_budget==Decimal("50.00000000")
def test_critical_quarantine():
    d=evaluate_model(model=m(),health=h(HealthState.BLOCKED,True,"DRIFT_CRITICAL"),evidence=e(),approved_risk_budget=Decimal("100"))
    assert d.status is GovernanceStatus.QUARANTINED and d.effective_risk_budget==0
def test_invalid_evidence_quarantine():
    d=evaluate_model(model=m(),health=h(),evidence=e(False,"EVIDENCE_EXPIRED"),approved_risk_budget=Decimal("100"))
    assert d.status is GovernanceStatus.QUARANTINED and d.effective_risk_budget==0
def test_challenger_live_blocked():
    d=evaluate_model(model=m(ModelRole.CHALLENGER,OperationalMode.LIVE),health=h(),evidence=e(),approved_risk_budget=Decimal("10"))
    assert d.status is GovernanceStatus.BLOCKED
def test_shadow_zero(): assert evaluate_model(model=m(ModelRole.CHALLENGER,OperationalMode.SHADOW),health=h(),evidence=e(),approved_risk_budget=Decimal("10")).effective_risk_budget==0
def test_invalidate():
    x=invalidate_promotion(model=m(),reason="REVOKED"); assert x.governance is GovernanceStatus.QUARANTINED and x.effective_risk_budget==0 and not x.evidence_valid
def test_single_champion():
    ChampionChallengerRegistry((m(),m(ModelRole.CHALLENGER,OperationalMode.SHADOW)))
def test_two_champions_rejected():
    import pytest
    m2=GovernedModel("m2","1",ModelRole.CHAMPION,OperationalMode.LIVE,DeploymentState.ACTIVE,HealthState.HEALTHY,GovernanceStatus.ELIGIBLE,True,True,Decimal("1"))
    with pytest.raises(ValueError,match="MULTIPLE_ACTIVE_CHAMPIONS"): ChampionChallengerRegistry((m(),m2))
def test_promote():
    c=GovernedModel("m2","1",ModelRole.CHALLENGER,OperationalMode.SHADOW,DeploymentState.ACTIVE,HealthState.HEALTHY,GovernanceStatus.ELIGIBLE,True,True,Decimal("10"))
    auth,dep=gate_ctx(); r=ChampionChallengerRegistry((m(),c)).promote("m2",validated=True,gate_authorization=auth,dependency_authority=dep,now=NOW)
    assert r.champion().model_id=="m2" and next(x for x in r.models if x.model_id=="m1").effective_risk_budget==0
def test_promote_requires_validation():
    import pytest
    c=GovernedModel("m2","1",ModelRole.CHALLENGER,OperationalMode.SHADOW,DeploymentState.ACTIVE,HealthState.HEALTHY,GovernanceStatus.ELIGIBLE,True,True,Decimal("10"))
    with pytest.raises(ValueError,match="PROMOTION_VALIDATION_REQUIRED"): ChampionChallengerRegistry((m(),c)).promote("m2",validated=False)
def test_quarantine_registry():
    r=ChampionChallengerRegistry((m(),)).quarantine("m1",reason="DRIFT_CRITICAL"); assert r.champion().effective_risk_budget==0
def test_monotonic():
    good=evaluate_model(model=m(),health=h(),evidence=e(),approved_risk_budget=Decimal("100"))
    bad=evaluate_model(model=m(),health=h(HealthState.BLOCKED,True,"DRIFT_CRITICAL"),evidence=e(),approved_risk_budget=Decimal("100"))
    assert bad.effective_risk_budget<=good.effective_risk_budget
def test_hash_deterministic():
    a=evaluate_model(model=m(),health=h(),evidence=e(),approved_risk_budget=Decimal("100"))
    b=evaluate_model(model=m(),health=h(),evidence=e(),approved_risk_budget=Decimal("100"))
    assert a.state_hash==b.state_hash

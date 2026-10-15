from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from trading_platform.promotion.contracts import *
from trading_platform.promotion.rollout import *
from trading_platform.promotion.compatibility import *
from trading_platform.operations.readiness import *
from trading_platform.security.permissions import *
from trading_platform.finalization import *
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from tests._m18_helpers import authorize_evidence_snapshot
from tests._m19_helpers import authorize_promotion_bundle

NOW=datetime.now(timezone.utc)

def bundle():
    return PromotionBundle('B1','S1','M1','F1','T1','C1','E1','CODE1','SNAP1',('G1','G2'),('h1','h2'),'A1',{'instrument':'BTCUSDT','venue':'BINANCE','mode':'CANARY'},'RB1', 'h', NOW)

def test_bundle_complete_and_scope():
    b=bundle(); b.validate()
    assert check_scope(b,{'instrument':'BTCUSDT'}).valid
    assert not check_scope(b,{'instrument':'ETHUSDT'}).valid

def test_approval_expiry():
    a=Approval('A',('reviewer',),NOW-timedelta(minutes=1),NOW+timedelta(minutes=1),{})
    a.validate(NOW)
    with pytest.raises(ValueError): a.validate(NOW+timedelta(minutes=2))

def test_gate_summary():
    authority=DependencyInvalidationLedger(EventStore())
    assert GateSummary(('G1','G2'),('G1','G2'),()).all_required_passed(authority)
    assert not GateSummary(('G1','G2'),('G1',),()).all_required_passed(authority)
    assert not GateSummary(('G1',),('G1',),('G1',)).all_required_passed(authority)

def test_promotion_requires_everything():
    a=Approval('A',('r',),NOW-timedelta(seconds=1),NOW+timedelta(hours=1),{})
    gs=GateSummary(('G1','G2'),('G1','G2'),())
    store=EventStore(); dep=DependencyInvalidationLedger(store); authorize_evidence_snapshot(store, bundle(), now=NOW); bundle_auth=authorize_promotion_bundle(store, bundle(), now=NOW)
    assert promotion_allowed(bundle=bundle(),gates=gs,approval=a,evidence_valid=True,compatibility_valid=True,scope=ScopeCheck(True,'ok'),artifacts_integrity=True,now=NOW,dependency_authority=dep,promotion_bundle_authorization_id=bundle_auth.authorization_id)
    assert not promotion_allowed(bundle=bundle(),gates=gs,approval=a,evidence_valid=False,compatibility_valid=True,scope=ScopeCheck(True,'ok'),artifacts_integrity=True,now=NOW,dependency_authority=dep,promotion_bundle_authorization_id=bundle_auth.authorization_id)

def test_compatibility_unknown_blocks():
    report=CompatibilityReport(*(Compatibility.COMPATIBLE,)*7)
    assert report.overall()==Compatibility.COMPATIBLE
    assert_deployable(report)
    bad=CompatibilityReport(Compatibility.UNKNOWN,*((Compatibility.COMPATIBLE,)*6))
    with pytest.raises(ValueError): assert_deployable(bad)

def test_shadow_has_zero_risk_and_no_orders():
    policy=RolloutPolicy(Decimal('100'),Decimal('1000'))
    state=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.SHADOW,DeploymentState.ACTIVE,'HEALTHY',True)
    assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('0'),exposure=Decimal('0'))
    assert shadow_orders_allowed() is False
    with pytest.raises(ValueError): assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('1'),exposure=Decimal('0'))

def test_canary_hard_bounds():
    policy=RolloutPolicy(Decimal('10'),Decimal('100'))
    state=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.CANARY,DeploymentState.ACTIVE,'HEALTHY',True)
    assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('10'),exposure=Decimal('100'))
    with pytest.raises(ValueError): assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('11'),exposure=Decimal('100'))

def test_live_requires_champion():
    policy=RolloutPolicy(Decimal('10'),Decimal('100'))
    state=RuntimeBundleState(ModelRole.CHALLENGER,OperationalMode.LIVE,DeploymentState.ACTIVE,'HEALTHY',True)
    with pytest.raises(ValueError): assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('0'),exposure=Decimal('0'))
    champion=RuntimeBundleState(ModelRole.CHAMPION,OperationalMode.LIVE,DeploymentState.ACTIVE,'HEALTHY',True)
    assert_runtime_activation(champion,policy=policy,allocated_risk=Decimal('0'),exposure=Decimal('0'))

def test_unhealthy_blocks():
    policy=RolloutPolicy(Decimal('10'),Decimal('100'))
    state=RuntimeBundleState(ModelRole.CHAMPION,OperationalMode.LIVE,DeploymentState.ACTIVE,'FAILED',True)
    with pytest.raises(ValueError): assert_runtime_activation(state,policy=policy,allocated_risk=Decimal('0'),exposure=Decimal('0'))

def test_research_permission_boundary():
    with pytest.raises(PermissionError): assert_capability('RESEARCH',Capability.PRODUCTION_TRADING)
    assert_capability('RESEARCH',Capability.BACKTEST)

def test_readiness_and_kill_switch():
    good=OperationalReadiness(*([True]*19))
    assert good.status()==ReadinessStatus.READY_FOR_LIVE
    bad=OperationalReadiness(*([True]*18+[False]))
    assert bad.status()==ReadinessStatus.BLOCKED
    kill=KillSwitch(True,NOW,'incident','ops')
    assert activation_blocked_by_kill(kill)

def test_production_entry_guard():
    assert not production_entry_allowed(readiness=True,promotion=True,approval=True,kill_switch=True,reconciliation_ok=True)
    assert production_entry_allowed(readiness=True,promotion=True,approval=True,kill_switch=False,reconciliation_ok=True)

def test_deterministic_id():
    assert deterministic_id('X',{'b':2,'a':1})==deterministic_id('X',{'a':1,'b':2})

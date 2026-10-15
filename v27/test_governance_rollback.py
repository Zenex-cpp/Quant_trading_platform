from decimal import Decimal
from datetime import datetime, timedelta, timezone
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v334.champion_authority import ChampionGateAuthorityLedger
import pytest
from trading_platform.v25.health import HealthState
from trading_platform.v26.governance import GovernanceStatus, GovernedModel, ChampionChallengerRegistry
from trading_platform.v27.governance import GovernanceController, GovernanceEventType
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState

def model(mid, role, mode, risk=Decimal("100"), health=HealthState.HEALTHY, gov=GovernanceStatus.ELIGIBLE, ev=True, ap=True):
    return GovernedModel(mid,"1",role,mode,DeploymentState.ACTIVE,health,gov,ev,ap,risk)

def base():
    return GovernanceController(ChampionChallengerRegistry((model("c",ModelRole.CHAMPION,OperationalMode.LIVE), model("a",ModelRole.CHALLENGER,OperationalMode.SHADOW,Decimal("80")), model("b",ModelRole.CHALLENGER,OperationalMode.SHADOW,Decimal("70")))))
NOW=datetime(2026,9,23,tzinfo=timezone.utc)
def promote(x):
    store=EventStore(); dep=DependencyInvalidationLedger(store)
    auth,_=ChampionGateAuthorityLedger.authorize(authorization_id="CA1",model_id="a",model_version="1",candidate_id="a",required_gate_ids=("G1",),passed_gate_ids=("G1",),promotion_id="P1",valid_from=NOW,expires_at=NOW+timedelta(hours=1),reviewer="reviewer",recorded_at_ms=1,dependency_authority=dep,store=store)
    return x.promote("a",actor="op",validated=True,now_ns=1,gate_authorization=auth,dependency_authority=dep,now=NOW)

def test_promote_records_chain():
    x=promote(base())
    assert x.registry.champion().model_id=="a"
    assert x.chain.events[-1].event_type is GovernanceEventType.PROMOTION
    x.audit()

def test_rollback_restores_prior_candidate():
    x=promote(base())
    y, rb = x.rollback("c",actor="op",reason="REGRESSION",now_ns=2)
    assert y.registry.champion().model_id=="c"
    assert rb.from_model_id=="a" and rb.to_model_id=="c"
    assert y.registry.champion().effective_risk_budget==Decimal("100")
    assert next(m for m in y.registry.models if m.model_id=="a").effective_risk_budget==0
    y.audit()

def test_rollback_rejects_quarantined_target():
    x=promote(base())
    q=x.quarantine("c",actor="risk",reason="BAD_EVIDENCE",now_ns=2)
    with pytest.raises(ValueError, match="ROLLBACK_TARGET_UNSAFE"):
        q.rollback("c",actor="op",reason="RECOVER",now_ns=3)

def test_rollback_requires_reason():
    with pytest.raises(ValueError, match="ROLLBACK_REASON_REQUIRED"):
        base().rollback("a",actor="op",reason="",now_ns=1)

def test_chain_tamper_detected():
    x=promote(base())
    object.__setattr__(x.chain.events[0], "reason", "TAMPERED")
    with pytest.raises(ValueError, match="GOVERNANCE_CHAIN_INVALID"):
        x.audit()

def test_no_rollback_to_current():
    x=base()
    with pytest.raises(ValueError, match="ROLLBACK_TARGET_IS_CURRENT"):
        x.rollback("c",actor="op",reason="NOOP",now_ns=1)

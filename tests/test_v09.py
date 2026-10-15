from datetime import datetime, timezone, timedelta
import pytest
from trading_platform.research.ledger import Hypothesis, HypothesisStatus, ResearchCost, ResearchDecision
from trading_platform.research.anti_duplication import ExperimentSignature, compare_signature
from trading_platform.research.knowledge import KnowledgeBase, KnowledgeItem, KnowledgeStatus
from trading_platform.research.stopping import StoppingEvidence, should_stop
from trading_platform.research.edge import EdgeRecord, EdgeStatus
from trading_platform.evidence.graph import Evidence, EvidenceState, EvidenceDependencyGraph, EvidenceGraphNode, propagate_invalidation
from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.evidence.invalidation import suspend
from trading_platform.evidence.promotion_checks import PromotionPrerequisites, promotion_allowed
from trading_platform.gates.contracts import Gate, GateResult, invalidate_gate
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger
from trading_platform.promotion.contracts import PromotionBundle

NOW=datetime.now(timezone.utc)

def test_hypothesis_and_cost():
    h=Hypothesis('H1','momentum in trend','plausible','continuation','fails after costs',HypothesisStatus.OPEN,'r',NOW)
    assert h.status == HypothesisStatus.OPEN
    c=ResearchCost(1,1,1,1,1,1,1)
    assert c.total_cost == 7

def test_similarity_reuse():
    c=ExperimentSignature('btc trend momentum','d1','f1','t1','s1',('e1',))
    e=ExperimentSignature('btc trend momentum','d1','f1','t1','s1',('e0',))
    r=compare_signature(c,[e])
    assert r.similar and r.outcome=='REUSE'

def test_knowledge_immutable_and_query():
    kb=KnowledgeBase()
    i=KnowledgeItem('K1','momentum works in trend','SUPPORTED',('E1',),'BTC',NOW)
    kb.upsert_immutable(i)
    assert len(kb.query('momentum trend')) == 1
    with pytest.raises(ValueError): kb.upsert_immutable(KnowledgeItem('K1','different','DISPROVED',(),'',NOW))

def test_stopping():
    yes, reason=should_stop(StoppingEvidence(True,True,False,False,False))
    assert yes and reason=='DIMINISHING_RETURNS'
    assert should_stop(StoppingEvidence(False,False,False,False,False))==(False,'CONTINUE')

def test_edge_record():
    e=EdgeRecord('E','trend','H','continuation',('EV',),('TREND',),('STRESS',),'HIGH','MEDIUM','WATCH','UNCERTAIN',EdgeStatus.WATCH)
    assert e.status == EdgeStatus.WATCH

def make_graph():
    g=EvidenceDependencyGraph()
    for n in [EvidenceGraphNode('D','DATASET','1',()),EvidenceGraphNode('F','FEATURE','1',('D',)),EvidenceGraphNode('X','EXPERIMENT','1',('F',)),EvidenceGraphNode('M','MODEL','1',('X',))]: g.add(n)
    return g

def test_evidence_graph_and_invalidation():
    g=make_graph()
    e=Evidence('EV','BACKTEST',EvidenceState.VALID,'1',NOW.isoformat(),('X',),('X',),'1',{'instrument':'BTC'},(None,None),'h','r')
    impact=propagate_invalidation(g,'D',{'EV':e},{'G1':('EV','M')},{'C1':('G1',)},{'P1':('C1',)})
    assert 'EV' in impact.invalidated_evidence and 'G1' in impact.invalidated_gates and 'P1' in impact.affected_promotions

def test_evidence_suspend():
    e=Evidence('EV','BACKTEST',EvidenceState.VALID,'1',NOW.isoformat(),(),(), '1',{},(None,None),'h','r')
    ev=suspend(e,'INC1',('EV',),('G1',),'bug')
    assert ev.new_state==EvidenceState.SUSPENDED

def test_snapshot_hash_deterministic():
    a=build_snapshot('S',('EV',),{'sharpe':1.0},('G1',),('M',),('V1',),('H1',),('METH',),('A1',),{'instrument':'BTC'})
    b=build_snapshot('S',('EV',),{'sharpe':1.0},('G1',),('M',),('V1',),('H1',),('METH',),('A1',),{'instrument':'BTC'})
    assert a.content_hash==b.content_hash

def test_gate_invalidation():
    g=Gate('G1','C1','R1',('V1',),('check',),GateResult.PASS,('A1',),('EV',),'o','r',NOW.isoformat(),None,'dep change')
    x=invalidate_gate(g,('V1','OTHER'))
    assert x.rerun_required and x.changed_dependencies==('V1',)

def test_promotion_prerequisites():
    store=EventStore(); dep=DependencyInvalidationLedger(store)
    snap=build_snapshot("S",("EV",),{"sharpe":1.0},("G1",),("B1",),("V1",),("H1",),("METH",),("A1",),{"instrument":"BTC"})
    EvidenceSnapshotAuthorityLedger(store).authorize(snapshot=snap,promotion_id="B1",bundle_id="B1",model_version="V1",valid_from=NOW-timedelta(minutes=1),expires_at=NOW+timedelta(hours=1),reviewer="reviewer",recorded_at_ms=1,dependency_authority=dep)
    bundle = PromotionBundle("B1","S1","V1","F1","T1","C1","E1","CODE1","S",("G1",),("H1",),"A1",{},"RB","HASH",NOW)
    bundle_auth,_ = PromotionBundleAuthorityLedger(store).authorize(authorization_id="PB-V09",bundle=bundle,valid_from=NOW-timedelta(minutes=1),expires_at=NOW+timedelta(hours=1),reviewer="reviewer",recorded_at_ms=2,dependency_authority=dep,store=store)
    assert promotion_allowed(PromotionPrerequisites(True,True,True,True,True,True,True), dependency_authority=dep, dependency_ids=("B1",), evidence_snapshot_id="S", promotion_id="B1", bundle_id="B1", model_version="V1", now=NOW, promotion_bundle_authorization_id=bundle_auth.authorization_id)
    assert not promotion_allowed(PromotionPrerequisites(True,True,False,True,True,True,True), dependency_authority=dep, dependency_ids=("B1",), evidence_snapshot_id="S", promotion_id="B1", bundle_id="B1", model_version="V1", now=NOW, promotion_bundle_authorization_id=bundle_auth.authorization_id)

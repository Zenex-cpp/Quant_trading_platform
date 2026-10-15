from datetime import datetime, timezone, timedelta
import pytest
from trading_platform.data.dataset import audit_ohlcv
from trading_platform.data.split import chronological_split
from trading_platform.data.leakage import scan
from trading_platform.data.lineage_graph import LineageGraph, LineageNode
from trading_platform.data.holdout import HoldoutPolicy, Workflow, HoldoutAccessContext
from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph
from trading_platform.evidence.graph import EvidenceGraphNode, EvidenceState
from trading_platform.v21.event_store import EventStore

UTC=timezone.utc
def dt(m): return datetime(2026,1,1,0,m,tzinfo=UTC)

def rows():
    return [
      {"event_time":"2026-01-01T00:00:00+00:00","symbol":"BTCUSDT","open":"100","high":"102","low":"99","close":"101","volume":"10"},
      {"event_time":"2026-01-01T00:01:00+00:00","symbol":"BTCUSDT","open":"101","high":"103","low":"100","close":"102","volume":"11"},
    ]

def test_ohlcv_audit_valid():
    r=audit_ohlcv(rows()); assert r.quality_status.value=="VALID"

def test_ohlcv_audit_invalid():
    x=rows(); x[0]["low"]="103"; r=audit_ohlcv(x); assert r.quality_status.value=="CRITICAL"

def test_leakage_future_availability_blocks():
    x={"prediction_time":dt(1),"available_at":dt(2),"event_time":dt(1)}
    assert scan(observations=[x]).blocked

def test_leakage_future_event_blocks():
    x={"prediction_time":dt(1),"available_at":dt(1),"event_time":dt(2)}
    assert scan(observations=[x]).blocked

def test_chronological_split_purges_and_holdout_exists():
    ends=[dt(0)+timedelta(minutes=i+2) for i in range(100)]
    s=chronological_split(100,label_end=ends,embargo=timedelta(minutes=1))
    assert s.train and s.validation and s.oos and s.final_holdout

def test_holdout_tuning_forbidden():
    store=EventStore()
    graph=EvidenceDependencyGraph()
    context=HoldoutAccessContext.build(
        store=store, graph=graph,
        evidence_index={"EV1": Evidence("EV1","RESEARCH",EvidenceState.VALID,"1","2026-01-01",("H1",),("H1",),"m",{},(None,None),"h","owner")},
        gate_dependencies={"G1": ("EV1",)}, candidates={"C1": ("G1",)}, promotions={"P1": ("C1",)},
    )
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_ACCESS_FORBIDDEN"):
        HoldoutPolicy("H1").authorize(Workflow.TUNING, context=context, access_id="A1", actor="research", attempted_at_ms=1)
    assert context.dependency_ledger.get("holdout-access-violation:A1") is not None

def test_lineage_requires_upstream_and_is_stable():
    g=LineageGraph(); g.add(LineageNode("d","DATASET","1",()))
    g.add(LineageNode("f","FEATURE","1",("d",)))
    h=g.version_hash(); assert h==g.version_hash(); assert g.dependents("d")==("f",)

def test_lineage_missing_upstream_blocked():
    g=LineageGraph()
    with pytest.raises(ValueError): g.add(LineageNode("f","FEATURE","1",("d",)))

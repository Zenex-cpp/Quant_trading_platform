from decimal import Decimal
from trading_platform.v21.event_store import EventStore
from trading_platform.v21.ledger import EventSourcedLedger
from trading_platform.v21.replay import DeterministicReplayer
from trading_platform.v21.temporal import TemporalIntegrity, TemporalState
from trading_platform.v21.reconciliation import reconcile_timeline, TemporalReconciliationState


def test_event_store_idempotent_and_chain_verified():
    s=EventStore()
    a=s.append(event_id="e1",occurred_at_ms=1,event_type="CASH_ADJUSTMENT",aggregate_id="A",payload={"amount":"100"})
    b=s.append(event_id="e1",occurred_at_ms=1,event_type="CASH_ADJUSTMENT",aggregate_id="A",payload={"amount":"100"})
    assert not a.duplicate and b.duplicate and s.verify_chain() and s.latest_sequence()==1


def test_event_sourced_ledger_rebuild_deterministic():
    s=EventStore()
    s.append(event_id="e1",occurred_at_ms=1,event_type="FILL",aggregate_id="BTCUSDT",payload={"side":"BUY","quantity":"2","price":"100"})
    s.append(event_id="e2",occurred_at_ms=2,event_type="FILL",aggregate_id="BTCUSDT",payload={"side":"SELL","quantity":"1","price":"110"})
    l=EventSourcedLedger(); st=l.rebuild(s)
    assert st.positions[0].quantity == Decimal("1")
    assert st.positions[0].realized_pnl == Decimal("10")
    r=DeterministicReplayer().replay(s)
    assert r.state == st


def test_temporal_gap_fail_closed_until_recovered():
    t=TemporalIntegrity()
    assert t.observe(1) is TemporalState.CONTIGUOUS
    assert t.observe(3) is TemporalState.GAP_SUSPECTED
    t.require_recovery(); assert t.state is TemporalState.RECOVERY_REQUIRED
    t.recovered(); assert t.state is TemporalState.CONTIGUOUS


def test_temporal_reconciliation_requires_all_three_views():
    rest={"openOrders":[],"positions":[{"symbol":"BTCUSDT","positionAmt":"1"}]}
    stream={"openOrders":[],"positions":[{"symbol":"BTCUSDT","positionAmt":"1"}]}
    ledger={"positions":[{"symbol":"BTCUSDT","quantity":"1"}]}
    x=reconcile_timeline(rest_snapshot=rest,stream_snapshot=stream,ledger_projection=ledger,stream_healthy=True,gap_free=True)
    assert x.state is TemporalReconciliationState.VERIFIED and x.trading_allowed
    y=reconcile_timeline(rest_snapshot=rest,stream_snapshot=stream,ledger_projection=ledger,stream_healthy=True,gap_free=False)
    assert y.state is TemporalReconciliationState.RECOVERY_REQUIRED and not y.trading_allowed

from trading_platform.v21.event_store import EventStore
from trading_platform.v21.ledger import EventSourcedLedger
from trading_platform.v22.checkpoint import CheckpointStore
from trading_platform.v22.incremental import IncrementalReplayer

def ev(store, eid, qty):
    return store.append(event_id=eid, occurred_at_ms=qty, event_type="FILL", aggregate_id="BTCUSDT", payload={"side":"BUY","quantity":str(qty),"price":"100"})

def test_checkpoint_is_anchored_and_verifiable():
    s=EventStore(); ev(s,"e1",1); l=EventSourcedLedger(); l.rebuild(s)
    cs=CheckpointStore(s); cp=cs.create("c1", l.state())
    assert cp.event_sequence == 1 and cs.verify(cp)

def test_incremental_replay_matches_full():
    s=EventStore(); ev(s,"e1",1); l=EventSourcedLedger(); l.rebuild(s); cs=CheckpointStore(s); cs.create("c1", l.state())
    ev(s,"e2",2)
    r=IncrementalReplayer().replay(s, cs)
    full=EventSourcedLedger(); full.rebuild(s)
    assert r.mode == "INCREMENTAL"
    assert r.state == full.state()
    assert r.applied_events == 1

def test_tampered_checkpoint_fails_closed():
    s=EventStore(); ev(s,"e1",1); l=EventSourcedLedger(); l.rebuild(s); cs=CheckpointStore(s); cp=cs.create("c1", l.state())
    s._db.execute("UPDATE checkpoints SET state_hash='bad' WHERE checkpoint_id='c1'"); s._db.commit()
    assert not cs.verify(cp)
    try: IncrementalReplayer().replay(s, cs)
    except RuntimeError as e: assert str(e)=="CHECKPOINT_INVALID"
    else: assert False

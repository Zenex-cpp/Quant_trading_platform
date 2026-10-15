from decimal import Decimal
from trading_platform.v21.event_store import EventStore
from trading_platform.v21.ledger import EventSourcedLedger
from trading_platform.v23.recovery import GapRecoveryCoordinator, RecoveryState, RestSnapshot, state_hash


def ev(store, eid, qty, ts):
    return store.append(event_id=eid, occurred_at_ms=ts, event_type="FILL", aggregate_id="BTCUSDT",
                        payload={"side":"BUY","quantity":str(qty),"price":"100"})


def snapshot_at(store, seq):
    l = EventSourcedLedger()
    for e in store.iter_events(start_sequence=1):
        if e.sequence > seq:
            break
        l.apply(e)
    return RestSnapshot.from_state("rs1", 1000 + seq, seq, l.state())


def test_rest_snapshot_plus_suffix_reaches_exact_target():
    s = EventStore(); ev(s, "e1", 1, 1); snap = snapshot_at(s, 1); ev(s, "e2", 2, 2)
    full = EventSourcedLedger(); full.rebuild(s)
    out = GapRecoveryCoordinator(s).recover(recovery_id="r1", snapshot=snap, target_state=full.state())
    assert out.state is RecoveryState.VERIFIED
    assert out.applied_events == 1
    assert out.trading_allowed
    assert out.state_hash == state_hash(full.state())


def test_invalid_snapshot_blocks():
    s = EventStore(); ev(s, "e1", 1, 1); snap = snapshot_at(s, 1)
    object.__setattr__(snap, "source_hash", "bad")
    out = GapRecoveryCoordinator(s).recover(recovery_id="r2", snapshot=snap)
    assert out.state is RecoveryState.BLOCKED
    assert not out.trading_allowed
    try: GapRecoveryCoordinator(s).recover(recovery_id="r2", snapshot=snap)
    except Exception: pass


def test_snapshot_ahead_blocks():
    s = EventStore(); ev(s, "e1", 1, 1)
    snap = RestSnapshot.from_state("rs2", 1000, 2, EventSourcedLedger().state())
    out = GapRecoveryCoordinator(s).recover(recovery_id="r3", snapshot=snap)
    assert out.reason == "SNAPSHOT_AHEAD_OF_LEDGER"


def test_target_mismatch_blocks_new_risk():
    s = EventStore(); ev(s, "e1", 1, 1); snap = snapshot_at(s, 1); ev(s, "e2", 2, 2)
    wrong = EventSourcedLedger(); wrong.rebuild(EventStore())
    out = GapRecoveryCoordinator(s).recover(recovery_id="r4", snapshot=snap, target_state=wrong.state())
    assert out.state is RecoveryState.BLOCKED
    assert not out.trading_allowed


def test_verified_gate_is_required():
    s = EventStore(); ev(s, "e1", 1, 1); snap = snapshot_at(s, 1)
    c = GapRecoveryCoordinator(s)
    try: c.require_verified(); assert False
    except PermissionError as e: assert str(e) == "RECOVERY_NOT_VERIFIED"
    out = c.recover(recovery_id="r5", snapshot=snap)
    assert out.state is RecoveryState.VERIFIED
    c.require_verified()

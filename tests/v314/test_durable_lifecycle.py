from pathlib import Path
import pytest

from trading_platform.execution.lifecycle import OrderExecutionState
from trading_platform.v313.durable_correlation import DurableExecutionCorrelationStore
from trading_platform.v314.durable_lifecycle import (
    DurableExecutionRecovery,
    DurableOrderLifecycleStore,
    LifecycleConflict,
    LifecycleReplayError,
    RestartSafeLifecycleRegistry,
)


def test_lifecycle_persists_and_replays_after_restart(tmp_path: Path):
    db = tmp_path / "execution.db"
    corr = DurableExecutionCorrelationStore(db)
    corr.register(intent_id="i1", order_request_id="r1", client_order_id="cid-1", now_epoch=1.0)
    life = DurableOrderLifecycleStore(db)
    reg = RestartSafeLifecycleRegistry(life)
    reg.apply(intent_id="i1", target=OrderExecutionState.SUBMITTED, event_id="e1", idempotency_key="k1", observed_at_epoch=1.0)
    reg.apply(intent_id="i1", target=OrderExecutionState.ACKNOWLEDGED, event_id="e2", idempotency_key="k2", observed_at_epoch=2.0)
    assert life.state("i1") is OrderExecutionState.ACKNOWLEDGED
    life.close(); corr.close()

    corr2 = DurableExecutionCorrelationStore(db)
    life2 = DurableOrderLifecycleStore(db)
    recovered = DurableExecutionRecovery(correlation_store=corr2, lifecycle_store=life2).restore("i1")
    assert recovered.lifecycle is OrderExecutionState.ACKNOWLEDGED
    assert [e.target for e in recovered.lifecycle_events] == [OrderExecutionState.SUBMITTED, OrderExecutionState.ACKNOWLEDGED]
    corr2.close(); life2.close()


def test_idempotent_lifecycle_transition_is_stable_but_conflict_fails(tmp_path: Path):
    store = DurableOrderLifecycleStore(tmp_path / "life.db")
    store.apply(intent_id="i1", target=OrderExecutionState.SUBMITTED, event_id="e1", idempotency_key="k1", observed_at_epoch=1.0)
    assert store.apply(intent_id="i1", target=OrderExecutionState.SUBMITTED, event_id="e1", idempotency_key="k1", observed_at_epoch=2.0) is OrderExecutionState.SUBMITTED
    with pytest.raises(LifecycleConflict, match="LIFECYCLE_IDEMPOTENCY_CONFLICT"):
        store.apply(intent_id="i1", target=OrderExecutionState.ACKNOWLEDGED, event_id="different", idempotency_key="k1", observed_at_epoch=3.0)
    store.close()


def test_invalid_persisted_path_is_detected_on_replay(tmp_path: Path):
    store = DurableOrderLifecycleStore(tmp_path / "life.db")
    store._db.execute(
        "INSERT INTO lifecycle_events(intent_id,source_state,target_state,event_id,idempotency_key,observed_at_epoch) VALUES(?,?,?,?,?,?)",
        ("i1", "ACKNOWLEDGED", "FILLED", "e1", "k1", 1.0),
    )
    store._db.commit()
    with pytest.raises(LifecycleReplayError, match="LIFECYCLE_SOURCE_MISMATCH"):
        store.replay("i1")
    store.close()


def test_recovery_preserves_unknown_as_blocking_state(tmp_path: Path):
    db = tmp_path / "execution.db"
    corr = DurableExecutionCorrelationStore(db)
    corr.register(intent_id="i1", order_request_id="r1", client_order_id="cid-1", now_epoch=1.0)
    life = DurableOrderLifecycleStore(db)
    life.apply(intent_id="i1", target=OrderExecutionState.SUBMITTED, event_id="e1", idempotency_key="k1", observed_at_epoch=1.0)
    life.apply(intent_id="i1", target=OrderExecutionState.UNKNOWN, event_id="e2", idempotency_key="k2", observed_at_epoch=2.0)
    state = DurableExecutionRecovery(correlation_store=corr, lifecycle_store=life).assert_consistent("i1")
    assert state.lifecycle is OrderExecutionState.UNKNOWN
    life.close(); corr.close()

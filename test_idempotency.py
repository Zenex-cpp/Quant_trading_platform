import pytest
from trading_platform.events.idempotency import IdempotencyStore, Operation

def test_duplicate_no_side_effect():
    store = IdempotencyStore()
    op = Operation("k1", "ORDER_SUBMIT", "hash-a")
    assert store.execute_once(op, "RESULT") == "RESULT"
    assert store.execute_once(op, "DIFFERENT") == "RESULT"

def test_collision_blocks():
    store = IdempotencyStore()
    store.execute_once(Operation("k1", "ORDER_SUBMIT", "hash-a"), "RESULT")
    with pytest.raises(RuntimeError):
        store.execute_once(Operation("k1", "ORDER_SUBMIT", "hash-b"), "RESULT")

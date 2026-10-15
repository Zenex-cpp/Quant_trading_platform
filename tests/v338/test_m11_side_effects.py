from pathlib import Path

import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v338.side_effects import (
    DurableSideEffectExecutor,
    DurableSideEffectLedger,
    SideEffectConflict,
    SideEffectReplayError,
    SideEffectRetryBlocked,
    SideEffectState,
)
from tests._immutable_test_helpers import tamper_event_store


def executor(path: Path):
    ledger = DurableSideEffectLedger(EventStore(str(path)))
    return ledger, DurableSideEffectExecutor(ledger)


def encode(value):
    return {"value": value}


def decode(payload):
    return payload["value"]


def test_success_is_replayed_after_restart_without_second_execution(tmp_path: Path):
    calls = []
    _, first = executor(tmp_path / "side_effect.db")
    assert first.execute(
        operation_id="op-1", operation_type="TEST_EFFECT", idempotency_key="k-1",
        payload_fingerprint="fp-1", started_at_ms=10,
        execute=lambda: calls.append("call") or "RESULT",
        encode_result=encode, decode_result=decode,
    ) == "RESULT"
    _, fresh = executor(tmp_path / "side_effect.db")
    assert fresh.execute(
        operation_id="op-1", operation_type="TEST_EFFECT", idempotency_key="k-1",
        payload_fingerprint="fp-1", started_at_ms=20,
        execute=lambda: calls.append("DUPLICATE") or "OTHER",
        encode_result=encode, decode_result=decode,
    ) == "RESULT"
    assert calls == ["call"]


def test_started_crash_window_blocks_retry_after_restart(tmp_path: Path):
    store = EventStore(str(tmp_path / "side_effect.db"))
    ledger = DurableSideEffectLedger(store)
    ledger.begin(
        operation_id="op-2", operation_type="TEST_EFFECT", idempotency_key="k-2",
        payload_fingerprint="fp-2", started_at_ms=10,
    )
    _, fresh = executor(tmp_path / "side_effect.db")
    with pytest.raises(SideEffectRetryBlocked, match="STARTED"):
        fresh.execute(
            operation_id="op-2", operation_type="TEST_EFFECT", idempotency_key="k-2",
            payload_fingerprint="fp-2", started_at_ms=20,
            execute=lambda: pytest.fail("duplicate side effect"),
            encode_result=encode, decode_result=decode,
        )


def test_unknown_outcome_blocks_retry(tmp_path: Path):
    _, first = executor(tmp_path / "side_effect.db")
    with pytest.raises(RuntimeError, match="transport"):
        first.execute(
            operation_id="op-3", operation_type="TEST_EFFECT", idempotency_key="k-3",
            payload_fingerprint="fp-3", started_at_ms=10,
            execute=lambda: (_ for _ in ()).throw(RuntimeError("transport")),
            encode_result=encode, decode_result=decode,
        )
    ledger, fresh = executor(tmp_path / "side_effect.db")
    rec = ledger.get("op-3")
    assert rec is not None and rec.state is SideEffectState.UNKNOWN
    with pytest.raises(SideEffectRetryBlocked, match="UNKNOWN"):
        fresh.execute(
            operation_id="op-3", operation_type="TEST_EFFECT", idempotency_key="k-3",
            payload_fingerprint="fp-3", started_at_ms=20,
            execute=lambda: pytest.fail("duplicate side effect"),
            encode_result=encode, decode_result=decode,
        )


def test_identity_collision_blocks(tmp_path: Path):
    ledger, _ = executor(tmp_path / "side_effect.db")
    ledger.begin(
        operation_id="op-4", operation_type="TEST_EFFECT", idempotency_key="k-4",
        payload_fingerprint="fp-a", started_at_ms=10,
    )
    with pytest.raises(SideEffectConflict, match="IDENTITY_CONFLICT"):
        ledger.begin(
            operation_id="op-4", operation_type="TEST_EFFECT", idempotency_key="k-4",
            payload_fingerprint="fp-b", started_at_ms=20,
        )


def test_secret_material_is_not_persisted(tmp_path: Path):
    store = EventStore(str(tmp_path / "side_effect.db"))
    ledger = DurableSideEffectLedger(store)
    executor = DurableSideEffectExecutor(ledger)
    secret = "SUPER_SECRET_DO_NOT_PERSIST"
    executor.execute(
        operation_id="op-5", operation_type="TEST_EFFECT", idempotency_key="k-5",
        payload_fingerprint="fp-5", started_at_ms=10,
        execute=lambda: {"exchange_order_id": "EX-5", "raw": secret},
        encode_result=lambda result: {"exchange_order_id": result["exchange_order_id"]},
        decode_result=lambda payload: payload["exchange_order_id"],
    )
    raw = "\n".join(str(event.payload) for event in store.iter_events())
    assert secret not in raw


def test_tampered_side_effect_chain_fails_closed(tmp_path: Path):
    store = EventStore(str(tmp_path / "side_effect.db"))
    ledger = DurableSideEffectLedger(store)
    ledger.begin(
        operation_id="op-6", operation_type="TEST_EFFECT", idempotency_key="k-6",
        payload_fingerprint="fp-6", started_at_ms=10,
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', 'side-effect:start:op-6'))
    with pytest.raises(SideEffectReplayError, match="SIDE_EFFECT_EVENT_CHAIN_INVALID"):
        ledger.get("op-6")

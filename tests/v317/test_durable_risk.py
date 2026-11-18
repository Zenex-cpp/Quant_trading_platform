from decimal import Decimal
from pathlib import Path
import pytest

from trading_platform.risk.budget import BudgetScope
from trading_platform.v21.event_store import EventStore
from trading_platform.v317 import (
    DurableRiskReservationBook,
    RiskReservationConflict,
    RiskReservationRecord,
    RiskReservationReplayError,
    RiskReservationState,
)
from trading_platform.events import EventSchemaRegistry
from trading_platform.v21.event_store import canonical_json
from tests._immutable_test_helpers import tamper_event_store
from tests.event_schema_support import event_schema_registry_for_tests, risk_reservation_book_for_tests


def record(rid="r1", aid="acct-hash", created=100, allowed="3"):
    return RiskReservationRecord(
        reservation_id=rid,
        scope=BudgetScope.ORDER,
        requested=Decimal(allowed),
        allowed=Decimal(allowed),
        intent_id="I1",
        risk_decision_id="R1",
        accounting_projection_hash=aid,
        created_at_ms=created,
        expires_at_ms=created + 1000,
    )


def test_persistent_book_requires_complete_schema_registry(tmp_path: Path):
    store = EventStore(str(tmp_path / "risk.db"))
    with pytest.raises(ValueError, match="RISK_EVENT_SCHEMA_REGISTRY_REQUIRED"):
        DurableRiskReservationBook(store, allocated=Decimal("10"))
    store.close()

    registry = event_schema_registry_for_tests()
    incomplete = EventSchemaRegistry((registry.get("RISK_BUDGET_INIT", "1.0"),))
    store = EventStore(str(tmp_path / "risk.db"))
    with pytest.raises(ValueError, match="RISK_EVENT_SCHEMA_REGISTRY_INCOMPLETE"):
        DurableRiskReservationBook(store, allocated=Decimal("10"), event_schema_registry=incomplete)
    store.close()


def test_reservation_payload_schema_fails_before_append_and_during_replay(tmp_path: Path):
    store = EventStore(str(tmp_path / "risk.db"))
    book = risk_reservation_book_for_tests(store, allocated=Decimal("10"))
    book.reserve(record())

    before = store.latest_sequence()
    with pytest.raises(ValueError, match="RISK_EVENT_SCHEMA_INVALID"):
        book.release("r1", reason=1, occurred_at_ms=101)
    assert store.latest_sequence() == before

    book.release("r1", reason="ORDER_REJECTED", occurred_at_ms=101)
    event = store.get("risk:release:r1")
    assert event is not None
    invalid_payload = {"reservation_id": "r1", "reason": 1}
    invalid_hash = store._compute_hash(
        event.sequence, event.event_id, event.occurred_at_ms, event.event_type,
        event.aggregate_id, invalid_payload, event.prev_hash,
    )
    tamper_event_store(
        store,
        "UPDATE events SET payload_json=?, event_hash=? WHERE event_id=?",
        (canonical_json(invalid_payload).decode(), invalid_hash, event.event_id),
    )
    assert store.verify_chain()
    with pytest.raises(RiskReservationReplayError, match="RISK_EVENT_SCHEMA_INVALID"):
        _ = book.projection


def test_restart_replays_reservation_and_budget(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b1 = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    snap = b1.reserve(record())
    assert snap.state is RiskReservationState.RESERVED
    assert b1.projection.remaining == Decimal("7")

    b2 = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    restored = b2.reservations()[0]
    assert restored == snap
    assert b2.projection.reserved == Decimal("3")


def test_same_reservation_retry_is_idempotent_and_conflict_is_rejected(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    first = b.reserve(record())
    second = b.reserve(record())
    assert first == second
    with pytest.raises(RiskReservationConflict, match="RESERVATION_ID_PAYLOAD_CONFLICT"):
        b.reserve(record(allowed="2"))


def test_consume_binds_intent_risk_and_accounting(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    b.reserve(record())
    with pytest.raises(RiskReservationConflict, match="RESERVATION_ACCOUNTING_HASH_STALE"):
        b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                  accounting_projection_hash="stale", occurred_at_ms=101)
    consumed = b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                         accounting_projection_hash="acct-hash", occurred_at_ms=101)
    assert consumed.state is RiskReservationState.CONSUMED
    assert b.projection.reserved == Decimal("0")
    assert b.projection.consumed == Decimal("3")


def test_double_consume_is_fail_closed(tmp_path: Path):
    b = risk_reservation_book_for_tests(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
              accounting_projection_hash="acct-hash", occurred_at_ms=101)
    with pytest.raises(RiskReservationConflict, match="RESERVATION_NOT_CONSUMABLE:CONSUMED"):
        b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                  accounting_projection_hash="acct-hash", occurred_at_ms=102)


def test_restart_preserves_consumed_no_retry_state(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    b.reserve(record())
    b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
              accounting_projection_hash="acct-hash", occurred_at_ms=101)
    b2 = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    assert b2.reservations()[0].state is RiskReservationState.CONSUMED


def test_budget_overdraw_is_rejected_without_mutation(tmp_path: Path):
    b = risk_reservation_book_for_tests(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("4"))
    b.reserve(record(rid="r1", allowed="3"))
    with pytest.raises(RiskReservationConflict, match="RISK_BUDGET_EXCEEDED"):
        b.reserve(record(rid="r2", allowed="2"))
    assert b.projection.reserved == Decimal("3")


def test_release_is_terminal_and_restart_safe(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    b.reserve(record())
    released = b.release("r1", reason="ORDER_REJECTED_BEFORE_SEND", occurred_at_ms=102)
    assert released.state is RiskReservationState.RELEASED
    b2 = risk_reservation_book_for_tests(EventStore(path), allocated=Decimal("10"))
    assert b2.reservations()[0].state is RiskReservationState.RELEASED
    assert b2.projection.remaining == Decimal("10")


def test_expired_reservation_cannot_be_consumed(tmp_path: Path):
    b = risk_reservation_book_for_tests(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    with pytest.raises(RiskReservationConflict, match="RESERVATION_EXPIRED"):
        b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                  accounting_projection_hash="acct-hash", occurred_at_ms=1100)
    assert b.reservations()[0].state is RiskReservationState.RESERVED


def test_reservation_cannot_be_expired_before_its_recorded_deadline(tmp_path: Path):
    b = risk_reservation_book_for_tests(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    with pytest.raises(RiskReservationConflict, match="RESERVATION_NOT_EXPIRED"):
        b.expire("r1", occurred_at_ms=1099)
    assert b.reservations()[0].state is RiskReservationState.RESERVED
    expired = b.expire("r1", occurred_at_ms=1100)
    assert expired.state is RiskReservationState.EXPIRED


def test_release_does_not_double_credit_remaining_budget(tmp_path: Path):
    b = risk_reservation_book_for_tests(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    assert b.projection.remaining == Decimal("7")
    b.release("r1", reason="ORDER_REJECTED", occurred_at_ms=101)
    assert b.projection.remaining == Decimal("10")

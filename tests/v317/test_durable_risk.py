from decimal import Decimal
from pathlib import Path
import pytest

from trading_platform.risk.budget import BudgetScope
from trading_platform.v21.event_store import EventStore
from trading_platform.v317 import (
    DurableRiskReservationBook,
    RiskReservationConflict,
    RiskReservationRecord,
    RiskReservationState,
)


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


def test_restart_replays_reservation_and_budget(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b1 = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    snap = b1.reserve(record())
    assert snap.state is RiskReservationState.RESERVED
    assert b1.projection.remaining == Decimal("7")

    b2 = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    restored = b2.reservations()[0]
    assert restored == snap
    assert b2.projection.reserved == Decimal("3")


def test_same_reservation_retry_is_idempotent_and_conflict_is_rejected(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    first = b.reserve(record())
    second = b.reserve(record())
    assert first == second
    with pytest.raises(RiskReservationConflict, match="RESERVATION_ID_PAYLOAD_CONFLICT"):
        b.reserve(record(allowed="2"))


def test_consume_binds_intent_risk_and_accounting(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
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
    b = DurableRiskReservationBook(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
              accounting_projection_hash="acct-hash", occurred_at_ms=101)
    with pytest.raises(RiskReservationConflict, match="RESERVATION_NOT_CONSUMABLE:CONSUMED"):
        b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                  accounting_projection_hash="acct-hash", occurred_at_ms=102)


def test_restart_preserves_consumed_no_retry_state(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    b.reserve(record())
    b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
              accounting_projection_hash="acct-hash", occurred_at_ms=101)
    b2 = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    assert b2.reservations()[0].state is RiskReservationState.CONSUMED


def test_budget_overdraw_is_rejected_without_mutation(tmp_path: Path):
    b = DurableRiskReservationBook(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("4"))
    b.reserve(record(rid="r1", allowed="3"))
    with pytest.raises(RiskReservationConflict, match="RISK_BUDGET_EXCEEDED"):
        b.reserve(record(rid="r2", allowed="2"))
    assert b.projection.reserved == Decimal("3")


def test_release_is_terminal_and_restart_safe(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    b = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    b.reserve(record())
    released = b.release("r1", reason="ORDER_REJECTED_BEFORE_SEND", occurred_at_ms=102)
    assert released.state is RiskReservationState.RELEASED
    b2 = DurableRiskReservationBook(EventStore(path), allocated=Decimal("10"))
    assert b2.reservations()[0].state is RiskReservationState.RELEASED
    assert b2.projection.remaining == Decimal("10")


def test_expired_reservation_cannot_be_consumed(tmp_path: Path):
    b = DurableRiskReservationBook(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    with pytest.raises(RiskReservationConflict, match="RESERVATION_EXPIRED"):
        b.consume("r1", intent_id="I1", risk_decision_id="R1", requested_risk=Decimal("3"),
                  accounting_projection_hash="acct-hash", occurred_at_ms=1100)
    assert b.reservations()[0].state is RiskReservationState.RESERVED


def test_release_does_not_double_credit_remaining_budget(tmp_path: Path):
    b = DurableRiskReservationBook(EventStore(str(tmp_path / "risk.db")), allocated=Decimal("10"))
    b.reserve(record())
    assert b.projection.remaining == Decimal("7")
    b.release("r1", reason="ORDER_REJECTED", occurred_at_ms=101)
    assert b.projection.remaining == Decimal("10")

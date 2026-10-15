from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.budget import BudgetScope
from trading_platform.v21.event_store import EventStore
from trading_platform.v317.durable_risk import (
    DurableRiskReservationBook,
    RiskReservationConflict,
    RiskReservationRecord,
    RiskReservationState,
)


def record(rid="R20", expires=100000):
    return RiskReservationRecord(rid, BudgetScope.ORDER, Decimal("3"), Decimal("3"), "I20", "RD20", "A20", 100, expires)


def setup(path: Path):
    b = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
    b.reserve(record())


def test_concurrent_consume_consume_has_one_terminal_event(tmp_path):
    path = tmp_path / "risk.db"
    setup(path)

    def worker():
        book = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
        try:
            return book.consume("R20", intent_id="I20", risk_decision_id="RD20", requested_risk=Decimal("3"), accounting_projection_hash="A20", occurred_at_ms=101)
        except RiskReservationConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        out = list(pool.map(lambda _: worker(), (1, 2)))

    assert sum(isinstance(v, RiskReservationConflict) for v in out) in (0, 1)
    restored = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
    assert restored.reservations()[0].state is RiskReservationState.CONSUMED
    consumed = [e for e in restored.store.iter_events() if e.event_type == restored.CONSUMED]
    assert len(consumed) == 1


@pytest.mark.parametrize("terminal", ["release", "expire", "override"])
def test_consume_races_other_terminal_transition(tmp_path, terminal):
    path = tmp_path / f"risk_{terminal}.db"
    setup(path)

    def consume_worker():
        book = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
        try:
            return ("consume", book.consume("R20", intent_id="I20", risk_decision_id="RD20", requested_risk=Decimal("3"), accounting_projection_hash="A20", occurred_at_ms=101))
        except RiskReservationConflict as exc:
            return ("consume_error", str(exc))

    def terminal_worker():
        book = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
        fn = {"release": lambda: book.release("R20", reason="TEST", occurred_at_ms=101),
              "expire": lambda: book.expire("R20", occurred_at_ms=101),
              "override": lambda: book.override("R20", reason="TEST", occurred_at_ms=101)}[terminal]
        try:
            return (terminal, fn())
        except RiskReservationConflict as exc:
            return (f"{terminal}_error", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(consume_worker)
        b = pool.submit(terminal_worker)
        results = [a.result(), b.result()]

    restored = DurableRiskReservationBook(EventStore(str(path)), allocated=Decimal("10"))
    snaps = restored.reservations()
    assert len(snaps) == 1
    assert snaps[0].state in {
        RiskReservationState.CONSUMED,
        RiskReservationState.RELEASED,
        RiskReservationState.EXPIRED,
        RiskReservationState.OVERRIDDEN,
    }
    terminals = [e for e in restored.store.iter_events() if e.event_type in {restored.CONSUMED, restored.RELEASED, restored.EXPIRED, restored.OVERRIDDEN}]
    assert len(terminals) == 1

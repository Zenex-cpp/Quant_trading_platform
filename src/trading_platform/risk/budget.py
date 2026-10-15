from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

class BudgetScope(str, Enum):
    SYSTEM="SYSTEM"
    PORTFOLIO="PORTFOLIO"
    STRATEGY="STRATEGY"
    MODEL="MODEL"
    TRADE="TRADE"
    ORDER="ORDER"

@dataclass(frozen=True)
class RiskReservation:
    reservation_id: str
    scope: BudgetScope
    requested: Decimal
    allowed: Decimal
    status: str = "RESERVED"

@dataclass
class RiskBudgetLedger:
    allocated: Decimal
    reserved: Decimal = Decimal("0")
    consumed: Decimal = Decimal("0")
    released: Decimal = Decimal("0")
    expired: Decimal = Decimal("0")
    overridden: Decimal = Decimal("0")

    def remaining(self) -> Decimal:
        return self.allocated - self.reserved - self.consumed + self.released + self.expired + self.overridden

class RiskReservationBook:
    def __init__(self) -> None:
        self._reservations: dict[str, RiskReservation] = {}
        self._consumed: set[str] = set()
        self._released: set[str] = set()

    def reserve(self, reservation: RiskReservation, ledger: RiskBudgetLedger) -> None:
        if reservation.reservation_id in self._reservations:
            raise ValueError("RESERVATION_ALREADY_EXISTS")
        if reservation.requested < 0 or reservation.allowed < 0 or reservation.allowed > reservation.requested:
            raise ValueError("INVALID_RESERVATION")
        if reservation.allowed > ledger.remaining():
            raise ValueError("RISK_BUDGET_EXCEEDED")
        ledger.reserved += reservation.allowed
        self._reservations[reservation.reservation_id] = reservation

    def consume(self, reservation_id: str, ledger: RiskBudgetLedger) -> None:
        r = self._reservations.get(reservation_id)
        if r is None:
            raise ValueError("RESERVATION_NOT_FOUND")
        if reservation_id in self._consumed:
            raise ValueError("RESERVATION_DOUBLE_CONSUMPTION")
        if reservation_id in self._released:
            raise ValueError("RELEASED_RESERVATION_REUSE")
        ledger.reserved -= r.allowed
        ledger.consumed += r.allowed
        self._consumed.add(reservation_id)

    def release(self, reservation_id: str, ledger: RiskBudgetLedger) -> None:
        r = self._reservations.get(reservation_id)
        if r is None:
            raise ValueError("RESERVATION_NOT_FOUND")
        if reservation_id in self._consumed:
            raise ValueError("CONSUMED_RESERVATION_CANNOT_RELEASE")
        ledger.reserved -= r.allowed
        ledger.released += r.allowed
        self._released.add(reservation_id)

    def get(self, reservation_id: str) -> RiskReservation:
        return self._reservations[reservation_id]

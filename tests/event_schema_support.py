from pathlib import Path

from trading_platform.events import EventSchemaRegistry
from trading_platform.v315 import DurableAccountingLedger
from trading_platform.v317 import DurableRiskReservationBook


ROOT = Path(__file__).resolve().parents[1]


def event_schema_registry_for_tests() -> EventSchemaRegistry:
    return EventSchemaRegistry.from_csv(ROOT / "schemas/v5_event_schema_registry.csv")


def accounting_ledger_for_tests(store) -> DurableAccountingLedger:
    return DurableAccountingLedger(store, event_schema_registry=event_schema_registry_for_tests())


def risk_reservation_book_for_tests(store, *, allocated) -> DurableRiskReservationBook:
    return DurableRiskReservationBook(
        store,
        allocated=allocated,
        event_schema_registry=event_schema_registry_for_tests(),
    )

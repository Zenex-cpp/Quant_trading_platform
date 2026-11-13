from __future__ import annotations

import csv
from pathlib import Path

from trading_platform.v317.durable_risk import DurableRiskReservationBook


ROOT = Path(__file__).resolve().parents[1]


def test_v5_risk_reservation_flow_inventory_matches_durable_states_and_code():
    with (ROOT / "schemas/v5_risk_reservation_flow.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert [row["event_type"] for row in rows] == [
        DurableRiskReservationBook.BUDGET_INIT,
        DurableRiskReservationBook.RESERVED,
        DurableRiskReservationBook.CONSUMED,
        DurableRiskReservationBook.RELEASED,
        DurableRiskReservationBook.EXPIRED,
        DurableRiskReservationBook.OVERRIDDEN,
    ]
    assert all(all(value for value in row.values()) for row in rows)
    terminals = {"CONSUMED", "RELEASED", "EXPIRED", "OVERRIDDEN"}
    assert {row["to_state"] for row in rows[2:]} == terminals
    assert all(row["from_state"] == "RESERVED" for row in rows[2:])

    document = (ROOT / "docs/71_V5_RISK_RESERVATION_FLOW.md").read_text(encoding="utf-8")
    assert "SQLite `BEGIN IMMEDIATE`" in document
    assert "before the external submit" in document
    assert "pre-trade snapshot with the current accounting projection hash" in document
    assert "keep the reservation consumed" in document


def test_v5_final_submit_paths_require_persistent_reservation_and_accounting():
    dispatcher = (ROOT / "src/trading_platform/v311/dispatch_guard.py").read_text(encoding="utf-8")
    testnet = (ROOT / "src/trading_platform/v385/controlled_testnet_submit.py").read_text(encoding="utf-8")
    assert "RISK_RESERVATION_GATE_REQUIRED" in dispatcher
    assert "RISK_RESERVATION_LEDGER_NOT_PERSISTENT" in dispatcher
    assert "RISK_ACCOUNTING_AUTHORITY_REQUIRED" in dispatcher
    assert "RISK_RESERVATION_GATE_REQUIRED" in testnet
    assert "PRE_TRADE_ACCOUNTING_HASH_STALE" in testnet
    assert "DISPATCH_EVENT_STORE_NOT_PERSISTENT" in testnet

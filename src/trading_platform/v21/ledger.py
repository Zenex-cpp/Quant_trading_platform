from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping
from .event_store import EventStore, LedgerEvent

@dataclass(frozen=True)
class PositionState:
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")

@dataclass(frozen=True)
class LedgerState:
    cash: Decimal = Decimal("0")
    positions: tuple[PositionState, ...] = ()
    processed_event_ids: tuple[str, ...] = ()

class EventSourcedLedger:
    """Rebuildable accounting projection. Exchange-facing events are never silently overwritten."""
    FILL = "FILL"
    FUNDING = "FUNDING"
    FEE = "FEE"
    CASH_ADJUSTMENT = "CASH_ADJUSTMENT"

    def __init__(self) -> None:
        self._positions: dict[str, PositionState] = {}
        self._cash = Decimal("0")
        self._processed: set[str] = set()

    def apply(self, event: LedgerEvent) -> None:
        if event.event_id in self._processed:
            return
        p = event.payload
        if event.event_type == self.FILL:
            self._apply_fill(event.aggregate_id, p)
        elif event.event_type == self.FUNDING:
            self._cash += Decimal(str(p.get("amount", "0")))
        elif event.event_type == self.FEE:
            fee = Decimal(str(p.get("amount", "0")))
            self._cash -= fee
            symbol = str(p.get("symbol", event.aggregate_id))
            prior = self._positions.get(symbol, PositionState(symbol))
            self._positions[symbol] = PositionState(symbol, prior.quantity, prior.avg_entry_price, prior.realized_pnl, prior.fees + fee)
        elif event.event_type == self.CASH_ADJUSTMENT:
            self._cash += Decimal(str(p.get("amount", "0")))
        else:
            raise ValueError(f"UNSUPPORTED_LEDGER_EVENT:{event.event_type}")
        self._processed.add(event.event_id)

    def state(self) -> LedgerState:
        return LedgerState(self._cash, tuple(self._positions[k] for k in sorted(self._positions)), tuple(sorted(self._processed)))

    def rebuild(self, store: EventStore) -> LedgerState:
        self._positions.clear(); self._cash = Decimal("0"); self._processed.clear()
        for event in store.iter_events():
            self.apply(event)
        return self.state()

    def _apply_fill(self, symbol: str, p: Mapping[str, Any]) -> None:
        side = str(p["side"]).upper()
        qty = Decimal(str(p["quantity"]))
        price = Decimal(str(p["price"]))
        if qty <= 0 or price <= 0 or side not in {"BUY", "SELL"}:
            raise ValueError("INVALID_FILL")
        prior = self._positions.get(symbol, PositionState(symbol))
        signed = qty if side == "BUY" else -qty
        old_q = prior.quantity
        new_q = old_q + signed
        realized = prior.realized_pnl
        avg = prior.avg_entry_price
        if old_q == 0 or (old_q > 0 and signed > 0) or (old_q < 0 and signed < 0):
            base = abs(old_q) + abs(signed)
            avg = ((abs(old_q) * avg) + (abs(signed) * price)) / base if base else Decimal("0")
        else:
            closing = min(abs(old_q), abs(signed))
            direction = Decimal("1") if old_q > 0 else Decimal("-1")
            realized += closing * (price - avg) * direction
            if new_q == 0:
                avg = Decimal("0")
            elif (old_q > 0 and new_q < 0) or (old_q < 0 and new_q > 0):
                avg = price
        self._positions[symbol] = PositionState(symbol, new_q, avg, realized, prior.fees)

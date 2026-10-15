from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .event_store import EventStore, LedgerEvent, sha256_json
from .ledger import EventSourcedLedger, LedgerState

@dataclass(frozen=True)
class ReplayCheckpoint:
    event_sequence: int
    state_hash: str

@dataclass(frozen=True)
class ReplayResult:
    state: LedgerState
    checkpoint: ReplayCheckpoint
    event_count: int

class DeterministicReplayer:
    def replay(self, store: EventStore, *, from_sequence: int = 1) -> ReplayResult:
        if not store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")
        ledger = EventSourcedLedger()
        count = 0
        for event in store.iter_events(start_sequence=from_sequence):
            ledger.apply(event); count += 1
        state = ledger.state()
        payload = {
            "cash": str(state.cash),
            "positions": [
                {"symbol": p.symbol, "quantity": str(p.quantity), "avg_entry_price": str(p.avg_entry_price), "realized_pnl": str(p.realized_pnl), "fees": str(p.fees)}
                for p in state.positions
            ],
            "processed_event_ids": list(state.processed_event_ids),
        }
        return ReplayResult(state, ReplayCheckpoint(store.latest_sequence(), sha256_json(payload)), count)

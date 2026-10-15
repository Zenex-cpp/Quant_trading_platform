from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping
import json
from trading_platform.v21.ledger import LedgerState, PositionState
from trading_platform.v21.event_store import EventStore, LedgerEvent, sha256_json

@dataclass(frozen=True)
class LedgerCheckpoint:
    checkpoint_id: str
    event_sequence: int
    event_hash: str
    state_hash: str
    cash: str
    positions: tuple[dict[str, str], ...]
    processed_event_count: int

class CheckpointStore:
    """Durable immutable checkpoints anchored to a specific ledger event."""
    def __init__(self, store: EventStore) -> None:
        self.store = store
        self.store._db.execute("""CREATE TABLE IF NOT EXISTS checkpoints(
            checkpoint_id TEXT PRIMARY KEY,
            event_sequence INTEGER NOT NULL UNIQUE,
            event_hash TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL
        )""")
        self.store._db.execute("""CREATE TRIGGER IF NOT EXISTS deny_checkpoint_update
        BEFORE UPDATE ON checkpoints BEGIN
            SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_UPDATE_FORBIDDEN');
        END;""")
        self.store._db.execute("""CREATE TRIGGER IF NOT EXISTS deny_checkpoint_delete
        BEFORE DELETE ON checkpoints BEGIN
            SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_DELETE_FORBIDDEN');
        END;""")
        self.store._db.commit()

    def create(self, checkpoint_id: str, state: LedgerState, *, event_sequence: int | None = None, created_at_ms: int = 0) -> LedgerCheckpoint:
        seq = self.store.latest_sequence() if event_sequence is None else int(event_sequence)
        if seq < 0 or seq > self.store.latest_sequence():
            raise ValueError("INVALID_CHECKPOINT_SEQUENCE")
        anchor = next((e for e in self.store.iter_events(start_sequence=seq) if e.sequence == seq), None) if seq else None
        event_hash = anchor.event_hash if anchor else "GENESIS"
        positions = tuple({"symbol": p.symbol, "quantity": str(p.quantity), "avg_entry_price": str(p.avg_entry_price), "realized_pnl": str(p.realized_pnl), "fees": str(p.fees)} for p in state.positions)
        state_json = json.dumps({"cash": str(state.cash), "positions": positions, "processed_event_ids": list(state.processed_event_ids)}, sort_keys=True, separators=(",", ":"))
        state_hash = sha256_json(json.loads(state_json))
        try:
            self.store._db.execute("INSERT INTO checkpoints(checkpoint_id,event_sequence,event_hash,state_hash,state_json,created_at_ms) VALUES(?,?,?,?,?,?)", (checkpoint_id, seq, event_hash, state_hash, state_json, created_at_ms))
            self.store._db.commit()
        except Exception:
            self.store._db.rollback(); raise
        return LedgerCheckpoint(checkpoint_id, seq, event_hash, state_hash, str(state.cash), positions, len(state.processed_event_ids))

    def latest(self) -> LedgerCheckpoint | None:
        row = self.store._db.execute("SELECT checkpoint_id,event_sequence,event_hash,state_hash,state_json FROM checkpoints ORDER BY event_sequence DESC LIMIT 1").fetchone()
        return self._row(row) if row else None

    def get(self, checkpoint_id: str) -> LedgerCheckpoint | None:
        row = self.store._db.execute("SELECT checkpoint_id,event_sequence,event_hash,state_hash,state_json FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        return self._row(row) if row else None

    def verify(self, cp: LedgerCheckpoint) -> bool:
        if cp.event_sequence == 0:
            anchor = "GENESIS"
        else:
            event = next((e for e in self.store.iter_events(start_sequence=cp.event_sequence) if e.sequence == cp.event_sequence), None)
            if event is None or event.event_hash != cp.event_hash:
                return False
            anchor = event.event_hash
        row = self.store._db.execute("SELECT event_hash,state_hash,state_json FROM checkpoints WHERE checkpoint_id=?", (cp.checkpoint_id,)).fetchone()
        return bool(row and row[0] == anchor and row[0] == cp.event_hash and row[1] == cp.state_hash and sha256_json(json.loads(row[2])) == cp.state_hash)

    @staticmethod
    def _row(row: tuple[Any, ...]) -> LedgerCheckpoint:
        cid, seq, eh, sh, raw = row
        data = json.loads(raw)
        return LedgerCheckpoint(str(cid), int(seq), str(eh), str(sh), str(data["cash"]), tuple(data["positions"]), len(data["processed_event_ids"]))

def restore_state(cp: LedgerCheckpoint) -> LedgerState:
    positions = tuple(PositionState(p["symbol"], Decimal(p["quantity"]), Decimal(p["avg_entry_price"]), Decimal(p["realized_pnl"]), Decimal(p["fees"])) for p in cp.positions)
    # Processed IDs are intentionally not persisted in the public checkpoint surface; replay uses event range.
    return LedgerState(Decimal(cp.cash), positions, ())

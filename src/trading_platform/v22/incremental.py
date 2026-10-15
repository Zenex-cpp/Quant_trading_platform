from __future__ import annotations
from dataclasses import dataclass
from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v21.ledger import EventSourcedLedger, LedgerState
from .checkpoint import CheckpointStore, LedgerCheckpoint, restore_state

@dataclass(frozen=True)
class IncrementalReplayResult:
    state: LedgerState
    checkpoint: LedgerCheckpoint
    applied_events: int
    mode: str

class IncrementalReplayer:
    """Checkpoint-anchored replay. Falls back to full replay when no valid checkpoint exists."""
    def replay(self, store: EventStore, checkpoints: CheckpointStore, *, checkpoint_id: str | None = None) -> IncrementalReplayResult:
        if not store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")
        cp = checkpoints.get(checkpoint_id) if checkpoint_id else checkpoints.latest()
        ledger = EventSourcedLedger()
        mode = "FULL"
        start = 1
        if cp and checkpoints.verify(cp) and cp.event_sequence <= store.latest_sequence():
            state = restore_state(cp)
            ledger._cash = state.cash
            ledger._positions = {p.symbol: p for p in state.positions}
            # Reconstruct processed set only for the checkpoint range; event application is idempotent afterwards.
            for e in store.iter_events(start_sequence=1):
                if e.sequence > cp.event_sequence: break
                ledger._processed.add(e.event_id)
            start = cp.event_sequence + 1
            mode = "INCREMENTAL"
        elif cp:
            raise RuntimeError("CHECKPOINT_INVALID")
        applied = 0
        for event in store.iter_events(start_sequence=start):
            ledger.apply(event); applied += 1
        state = ledger.state()
        # Create an ephemeral deterministic result checkpoint; callers can persist it explicitly.
        payload = {"cash": str(state.cash), "positions": [{"symbol":p.symbol,"quantity":str(p.quantity),"avg_entry_price":str(p.avg_entry_price),"realized_pnl":str(p.realized_pnl),"fees":str(p.fees)} for p in state.positions], "processed_event_ids": list(state.processed_event_ids)}
        # No mutation here: the returned checkpoint is materialized by caller via CheckpointStore.create.
        result_cp = LedgerCheckpoint("UNPERSISTED", store.latest_sequence(), (next(iter(store.iter_events(start_sequence=store.latest_sequence())), None).event_hash if store.latest_sequence() else "GENESIS"), sha256_json(payload), str(state.cash), tuple({"symbol":p.symbol,"quantity":str(p.quantity),"avg_entry_price":str(p.avg_entry_price),"realized_pnl":str(p.realized_pnl),"fees":str(p.fees)} for p in state.positions), len(state.processed_event_ids))
        return IncrementalReplayResult(state, result_cp, applied, mode)

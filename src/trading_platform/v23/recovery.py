from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping
from trading_platform.v21.event_store import EventStore, LedgerEvent, sha256_json
from trading_platform.v21.ledger import EventSourcedLedger, LedgerState, PositionState

class RecoveryState(str, Enum):
    BLOCKED = "BLOCKED"
    RESTORED = "RESTORED"
    VERIFIED = "VERIFIED"

class RecoveryError(RuntimeError):
    pass

@dataclass(frozen=True)
class RestSnapshot:
    snapshot_id: str
    captured_at_ms: int
    last_event_sequence: int
    state: LedgerState
    source_hash: str

    @classmethod
    def from_state(cls, snapshot_id: str, captured_at_ms: int, last_event_sequence: int,
                   state: LedgerState, source_hash: str | None = None) -> "RestSnapshot":
        payload = state_payload(state)
        return cls(snapshot_id, captured_at_ms, last_event_sequence, state,
                   source_hash or sha256_json(payload))

    def verify(self) -> bool:
        return self.source_hash == sha256_json(state_payload(self.state))

@dataclass(frozen=True)
class GapInterval:
    from_sequence: int
    to_sequence: int

    def validate(self) -> None:
        if self.from_sequence < 0 or self.to_sequence < self.from_sequence:
            raise ValueError("INVALID_GAP_INTERVAL")

@dataclass(frozen=True)
class RecoveryResult:
    recovery_id: str
    state: RecoveryState
    snapshot_id: str
    snapshot_sequence: int
    replay_from_sequence: int
    replay_to_sequence: int
    applied_events: int
    state_hash: str
    expected_state_hash: str | None
    trading_allowed: bool
    reason: str


def state_payload(state: LedgerState) -> dict[str, Any]:
    return {
        "cash": str(state.cash),
        "positions": [
            {"symbol": p.symbol, "quantity": str(p.quantity),
             "avg_entry_price": str(p.avg_entry_price),
             "realized_pnl": str(p.realized_pnl), "fees": str(p.fees)}
            for p in state.positions
        ],
    }

def state_hash(state: LedgerState) -> str:
    return sha256_json(state_payload(state))

def project_events(events: Iterable[LedgerEvent], base: LedgerState | None = None) -> LedgerState:
    ledger = EventSourcedLedger()
    if base is not None:
        ledger._cash = base.cash
        ledger._positions = {p.symbol: p for p in base.positions}
    for event in events:
        ledger.apply(event)
    return ledger.state()

class GapRecoveryCoordinator:
    """Fail-closed recovery: verified REST snapshot + contiguous ledger suffix + deterministic target proof."""
    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._verified = False
        self._last: RecoveryResult | None = None

    def recover(self, *, recovery_id: str, snapshot: RestSnapshot,
                target_state: LedgerState | None = None,
                require_chain: bool = True) -> RecoveryResult:
        self._verified = False
        if require_chain and not self.store.verify_chain():
            return self._blocked(recovery_id, snapshot, "EVENT_CHAIN_INVALID")
        if not snapshot.verify():
            return self._blocked(recovery_id, snapshot, "REST_SNAPSHOT_INVALID")
        latest = self.store.latest_sequence()
        if snapshot.last_event_sequence > latest:
            return self._blocked(recovery_id, snapshot, "SNAPSHOT_AHEAD_OF_LEDGER")

        expected_next = snapshot.last_event_sequence + 1
        suffix = list(self.store.iter_events(start_sequence=expected_next))
        if suffix and suffix[0].sequence != expected_next:
            return self._blocked(recovery_id, snapshot, "EVENT_GAP_UNRESOLVED")
        for prev, cur in zip(suffix, suffix[1:]):
            if cur.sequence != prev.sequence + 1 or cur.prev_hash != prev.event_hash:
                return self._blocked(recovery_id, snapshot, "EVENT_SUFFIX_NOT_CONTIGUOUS")

        rebuilt = project_events(suffix, snapshot.state)
        rebuilt_hash = state_hash(rebuilt)
        expected_hash = state_hash(target_state) if target_state is not None else None
        if expected_hash is not None and rebuilt_hash != expected_hash:
            return self._blocked(recovery_id, snapshot, "RECOVERED_STATE_MISMATCH",
                                  state_hash_value=rebuilt_hash, expected_state_hash=expected_hash,
                                  applied_events=len(suffix))

        result = RecoveryResult(
            recovery_id=recovery_id, state=RecoveryState.VERIFIED,
            snapshot_id=snapshot.snapshot_id, snapshot_sequence=snapshot.last_event_sequence,
            replay_from_sequence=expected_next,
            replay_to_sequence=latest,
            applied_events=len(suffix), state_hash=rebuilt_hash,
            expected_state_hash=expected_hash, trading_allowed=True,
            reason="REST_SNAPSHOT_PLUS_CONTIGUOUS_SUFFIX_VERIFIED",
        )
        self._last = result
        self._verified = True
        return result

    def require_verified(self) -> None:
        if not self._verified:
            raise PermissionError("RECOVERY_NOT_VERIFIED")

    def last_result(self) -> RecoveryResult | None:
        return self._last

    def _blocked(self, recovery_id: str, snapshot: RestSnapshot, reason: str,
                 *, state_hash_value: str = "", expected_state_hash: str | None = None,
                 applied_events: int = 0) -> RecoveryResult:
        result = RecoveryResult(
            recovery_id=recovery_id, state=RecoveryState.BLOCKED,
            snapshot_id=snapshot.snapshot_id, snapshot_sequence=snapshot.last_event_sequence,
            replay_from_sequence=snapshot.last_event_sequence + 1,
            replay_to_sequence=self.store.latest_sequence(), applied_events=applied_events,
            state_hash=state_hash_value, expected_state_hash=expected_state_hash,
            trading_allowed=False, reason=reason,
        )
        self._last = result
        return result

@dataclass(frozen=True)
class RecoveryProof:
    recovery_id: str
    snapshot_hash: str
    recovered_hash: str
    target_hash: str | None
    event_chain_verified: bool
    suffix_contiguous: bool
    exact_match: bool

    @property
    def passed(self) -> bool:
        return self.event_chain_verified and self.suffix_contiguous and self.exact_match

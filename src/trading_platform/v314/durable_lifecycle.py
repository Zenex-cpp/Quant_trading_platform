from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterable

from trading_platform.execution.lifecycle import OrderExecutionState, OrderLifecycle, OrderTransition
from trading_platform.v313.durable_correlation import DurableExecutionCorrelationStore, CorrelationRecord


class LifecycleConflict(ValueError):
    pass


class LifecycleReplayError(ValueError):
    pass


@dataclass(frozen=True)
class LifecycleEventRecord:
    seq: int
    intent_id: str
    source: OrderExecutionState
    target: OrderExecutionState
    event_id: str
    idempotency_key: str
    observed_at_epoch: float


@dataclass(frozen=True)
class RestoredExecutionState:
    correlation: CorrelationRecord
    lifecycle: OrderExecutionState
    lifecycle_events: tuple[LifecycleEventRecord, ...]
    journal_event_count: int


class DurableOrderLifecycleStore:
    """Persistent, replayable order lifecycle independent from RAM state.

    The store records every accepted transition in sequence order. A fresh process can
    reconstruct an OrderLifecycle solely from durable transitions and verify that the
    persisted path is still a valid state machine path. Credentials and transports are
    never persisted.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS lifecycle_events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL, "
            "source_state TEXT NOT NULL, target_state TEXT NOT NULL, event_id TEXT NOT NULL, "
            "idempotency_key TEXT NOT NULL, observed_at_epoch REAL NOT NULL, "
            "UNIQUE(intent_id, idempotency_key)"
            ")"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_intent ON lifecycle_events(intent_id, seq)")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _rows(self, intent_id: str) -> list[LifecycleEventRecord]:
        rows = self._db.execute(
            "SELECT seq,intent_id,source_state,target_state,event_id,idempotency_key,observed_at_epoch "
            "FROM lifecycle_events WHERE intent_id=? ORDER BY seq",
            (intent_id,),
        ).fetchall()
        out: list[LifecycleEventRecord] = []
        for row in rows:
            try:
                source = OrderExecutionState(row[2])
                target = OrderExecutionState(row[3])
            except ValueError as exc:
                raise LifecycleReplayError("UNKNOWN_PERSISTED_LIFECYCLE_STATE") from exc
            out.append(LifecycleEventRecord(int(row[0]), row[1], source, target, row[4], row[5], float(row[6])))
        return out

    def replay(self, intent_id: str) -> OrderLifecycle:
        lifecycle = OrderLifecycle()
        for rec in self._rows(intent_id):
            if rec.source is not lifecycle.state:
                raise LifecycleReplayError("LIFECYCLE_SOURCE_MISMATCH")
            try:
                lifecycle.apply(rec.target, event_id=rec.event_id, idempotency_key=rec.idempotency_key)
            except ValueError as exc:
                raise LifecycleReplayError("INVALID_PERSISTED_LIFECYCLE_PATH") from exc
        return lifecycle

    def events(self, intent_id: str) -> tuple[LifecycleEventRecord, ...]:
        return tuple(self._rows(intent_id))

    def state(self, intent_id: str) -> OrderExecutionState:
        return self.replay(intent_id).state

    def apply(self, *, intent_id: str, target: OrderExecutionState,
              event_id: str, idempotency_key: str, observed_at_epoch: float) -> OrderExecutionState:
        if not intent_id:
            raise ValueError("INTENT_ID_REQUIRED")
        if not event_id:
            raise ValueError("EVENT_ID_REQUIRED")
        if not idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        lifecycle = self.replay(intent_id)
        prior = self._db.execute(
            "SELECT event_id,target_state FROM lifecycle_events WHERE intent_id=? AND idempotency_key=?",
            (intent_id, idempotency_key),
        ).fetchone()
        if prior:
            if prior[0] != event_id or prior[1] != target.value:
                raise LifecycleConflict("LIFECYCLE_IDEMPOTENCY_CONFLICT")
            return lifecycle.state
        try:
            lifecycle.apply(target, event_id=event_id, idempotency_key=idempotency_key)
        except ValueError as exc:
            raise LifecycleConflict(str(exc)) from exc
        self._db.execute(
            "INSERT INTO lifecycle_events(intent_id,source_state,target_state,event_id,idempotency_key,observed_at_epoch) "
            "VALUES(?,?,?,?,?,?)",
            (intent_id, lifecycle._applied[idempotency_key].source.value, target.value,
             event_id, idempotency_key, float(observed_at_epoch)),
        )
        self._db.commit()
        return lifecycle.state


class RestartSafeLifecycleRegistry:
    """Small cache over DurableOrderLifecycleStore; restart requires no RAM state."""

    def __init__(self, store: DurableOrderLifecycleStore) -> None:
        self.store = store
        self._cache: dict[str, OrderLifecycle] = {}

    def apply(self, *, intent_id: str, target: OrderExecutionState,
              event_id: str, idempotency_key: str, observed_at_epoch: float) -> OrderExecutionState:
        state = self.store.apply(intent_id=intent_id, target=target, event_id=event_id,
                                 idempotency_key=idempotency_key, observed_at_epoch=observed_at_epoch)
        self._cache[intent_id] = self.store.replay(intent_id)
        return state

    def restore(self, intent_id: str) -> OrderLifecycle:
        lifecycle = self.store.replay(intent_id)
        self._cache[intent_id] = lifecycle
        return lifecycle

    def current(self, intent_id: str) -> OrderExecutionState:
        return self.store.state(intent_id)


class DurableExecutionRecovery:
    """Cross-check correlation, lifecycle replay and evidence journal after restart."""

    def __init__(self, *, correlation_store: DurableExecutionCorrelationStore,
                 lifecycle_store: DurableOrderLifecycleStore) -> None:
        self.correlation_store = correlation_store
        self.lifecycle_store = lifecycle_store

    def restore(self, intent_id: str) -> RestoredExecutionState:
        correlation = self.correlation_store.get_by_intent(intent_id)
        lifecycle = self.lifecycle_store.replay(intent_id)
        events = self.lifecycle_store.events(intent_id)
        journal = self.correlation_store.events_for_intent(intent_id)
        if events and events[0].intent_id != intent_id:
            raise LifecycleReplayError("LIFECYCLE_INTENT_MISMATCH")
        return RestoredExecutionState(
            correlation=correlation,
            lifecycle=lifecycle.state,
            lifecycle_events=events,
            journal_event_count=len(journal),
        )

    def assert_consistent(self, intent_id: str) -> RestoredExecutionState:
        state = self.restore(intent_id)
        if state.lifecycle is OrderExecutionState.UNKNOWN:
            # Consistency is a data-integrity statement only. UNKNOWN still blocks trading.
            return state
        if state.lifecycle is OrderExecutionState.CREATED and state.lifecycle_events:
            raise LifecycleReplayError("CREATED_WITH_PERSISTED_TRANSITIONS")
        return state

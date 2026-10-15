from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import sqlite3
from typing import Any, Callable, Mapping, Protocol

from trading_platform.v19.user_stream import (
    KeepalivePolicy,
    NormalizedUserEvent,
    StreamHealth,
    UserEventType,
    normalize_user_event,
)
from trading_platform.v36.user_execution import BinanceExecutionCorrelation, UserEventApplyResult
from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger, DispatchReconciliationConflict


class SessionState(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    RECONNECTING = "RECONNECTING"
    RECOVERING = "RECOVERING"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class RecoveryCause(str, Enum):
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"
    LISTEN_KEY_EXPIRED = "LISTEN_KEY_EXPIRED"
    ORDER_EVENT_OUT_OF_ORDER = "ORDER_EVENT_OUT_OF_ORDER"
    DUPLICATE_RESTART_REPLAY = "DUPLICATE_RESTART_REPLAY"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class StreamCheckpoint:
    event_type: str
    event_time_ms: int | None
    transaction_time_ms: int | None
    raw_hash: str
    accepted_count: int


@dataclass(frozen=True)
class PersistedStreamEvent:
    event_id: str
    event_type: str
    event_time_ms: int | None
    transaction_time_ms: int | None
    raw_hash: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class RecoveryAssessment:
    recovered: bool
    reason: str
    reconciled_orders: bool
    reconciled_positions: bool
    reconciled_accounting: bool

    @property
    def safe_for_trading(self) -> bool:
        return self.recovered and self.reconciled_orders and self.reconciled_positions and self.reconciled_accounting


class UserStreamRecovery(Protocol):
    def __call__(self, cause: RecoveryCause) -> RecoveryAssessment: ...


class DurableUserStreamStore:
    """Small SQLite journal for user-stream dedupe/checkpoints.

    The store persists only normalized operational evidence. Credentials and socket state
    are intentionally excluded. It is safe to reopen after process restart.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS stream_events ("
            "event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, event_time_ms INTEGER, "
            "transaction_time_ms INTEGER, raw_hash TEXT NOT NULL, payload_json TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS stream_checkpoints ("
            "event_type TEXT PRIMARY KEY, event_time_ms INTEGER, transaction_time_ms INTEGER, "
            "raw_hash TEXT NOT NULL, accepted_count INTEGER NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS stream_session ("
            "id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, listen_key TEXT, "
            "updated_epoch REAL NOT NULL, reason TEXT NOT NULL)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def event_id(event: NormalizedUserEvent) -> str:
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(payload).hexdigest()

    def has_event(self, event_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM stream_events WHERE event_id=?", (event_id,)).fetchone()
        return row is not None

    def append(self, event: NormalizedUserEvent) -> tuple[str, bool]:
        event_id = self.event_id(event)
        payload_json = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO stream_events(event_id,event_type,event_time_ms,transaction_time_ms,raw_hash,payload_json) "
            "VALUES(?,?,?,?,?,?)",
            (event_id, event.event_type.value, event.event_time_ms, event.transaction_time_ms, event.raw_hash, payload_json),
        )
        self._conn.commit()
        return event_id, cur.rowcount == 0

    def checkpoint(self, event: NormalizedUserEvent) -> StreamCheckpoint | None:
        row = self._conn.execute(
            "SELECT event_type,event_time_ms,transaction_time_ms,raw_hash,accepted_count "
            "FROM stream_checkpoints WHERE event_type=?", (event.event_type.value,)
        ).fetchone()
        if row is None:
            return None
        return StreamCheckpoint(*row)

    def set_checkpoint(self, event: NormalizedUserEvent, accepted_count: int) -> None:
        self._conn.execute(
            "INSERT INTO stream_checkpoints(event_type,event_time_ms,transaction_time_ms,raw_hash,accepted_count) "
            "VALUES(?,?,?,?,?) ON CONFLICT(event_type) DO UPDATE SET "
            "event_time_ms=excluded.event_time_ms, transaction_time_ms=excluded.transaction_time_ms, "
            "raw_hash=excluded.raw_hash, accepted_count=excluded.accepted_count",
            (event.event_type.value, event.event_time_ms, event.transaction_time_ms, event.raw_hash, accepted_count),
        )
        self._conn.commit()

    def session_state(self) -> tuple[SessionState, str | None, float, str] | None:
        row = self._conn.execute("SELECT state,listen_key,updated_epoch,reason FROM stream_session WHERE id=1").fetchone()
        if row is None:
            return None
        return SessionState(row[0]), row[1], float(row[2]), row[3]

    def set_session(self, state: SessionState, *, listen_key: str | None, now_epoch: float, reason: str) -> None:
        self._conn.execute(
            "INSERT INTO stream_session(id,state,listen_key,updated_epoch,reason) VALUES(1,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state,listen_key=excluded.listen_key,"
            "updated_epoch=excluded.updated_epoch,reason=excluded.reason",
            (state.value, listen_key, float(now_epoch), reason),
        )
        self._conn.commit()


@dataclass(frozen=True)
class UserStreamRuntimeState:
    state: SessionState
    stream_health: StreamHealth
    listen_key_present: bool
    trading_allowed: bool
    recovery_required: bool
    last_event_time_ms: int | None
    reason: str


class UserStreamSessionCoordinator:
    """Durable session state, reconnect safety and REST reconciliation gate.

    There is no sequence number in the Binance user-data schema used here. For a single
    connection and same event type, T/E ordering is therefore the hard local ordering
    signal. After disconnect/reconnect or listenKey expiry the coordinator requires an
    explicit REST reconciliation assessment before trading is enabled again.
    """

    def __init__(
        self,
        *,
        store: DurableUserStreamStore | None = None,
        correlation: BinanceExecutionCorrelation | None = None,
        keepalive_policy: KeepalivePolicy = KeepalivePolicy(),
        dispatch_reconciliation_ledger: DurableDispatchReconciliationLedger | None = None,
    ) -> None:
        self.store = store or DurableUserStreamStore()
        self.correlation = correlation or BinanceExecutionCorrelation()
        self.dispatch_reconciliation_ledger = dispatch_reconciliation_ledger
        self.policy = keepalive_policy
        self.policy.validate()
        persisted = self.store.session_state()
        if persisted:
            self.state = persisted[0]
            self.listen_key = persisted[1]
            self.last_reason = persisted[3]
        else:
            self.state = SessionState.NEW
            self.listen_key = None
            self.last_reason = "INITIAL"
        self.last_event_time_ms: int | None = None
        self.recovery_required = self.state not in {SessionState.NEW, SessionState.ACTIVE}
        self.last_recovery_cause = RecoveryCause.MANUAL
        self._last_event_by_type: dict[str, tuple[int, int]] = {}

    def start(self, *, listen_key: str, now_epoch: float) -> UserStreamRuntimeState:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        self.listen_key = listen_key
        self.state = SessionState.ACTIVE
        self.recovery_required = False
        self.last_recovery_cause = RecoveryCause.CONNECT
        self.last_reason = "STREAM_STARTED"
        self.store.set_session(self.state, listen_key=listen_key, now_epoch=now_epoch, reason=self.last_reason)
        return self.snapshot(now_epoch)

    def connected_after_reconnect(self, *, listen_key: str, now_epoch: float) -> UserStreamRuntimeState:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        self.listen_key = listen_key
        self.state = SessionState.RECOVERING
        self.recovery_required = True
        self.last_recovery_cause = RecoveryCause.DISCONNECT
        self.last_reason = "RECONNECT_REQUIRES_RECONCILIATION"
        self.store.set_session(self.state, listen_key=listen_key, now_epoch=now_epoch, reason=self.last_reason)
        return self.snapshot(now_epoch)

    def disconnected(self, *, now_epoch: float) -> UserStreamRuntimeState:
        if self.state is SessionState.CLOSED:
            raise PermissionError("STREAM_CLOSED")
        self.state = SessionState.RECONNECTING
        self.recovery_required = True
        self.last_recovery_cause = RecoveryCause.DISCONNECT
        self.last_reason = "STREAM_DISCONNECTED"
        self.store.set_session(self.state, listen_key=self.listen_key, now_epoch=now_epoch, reason=self.last_reason)
        return self.snapshot(now_epoch)

    def listen_key_expired(self, *, now_epoch: float) -> UserStreamRuntimeState:
        self.state = SessionState.EXPIRED
        self.listen_key = None
        self.recovery_required = True
        self.last_recovery_cause = RecoveryCause.LISTEN_KEY_EXPIRED
        self.last_reason = "LISTEN_KEY_EXPIRED"
        self.store.set_session(self.state, listen_key=None, now_epoch=now_epoch, reason=self.last_reason)
        return self.snapshot(now_epoch)

    def close(self, *, now_epoch: float) -> None:
        self.state = SessionState.CLOSED
        self.recovery_required = True
        self.last_reason = "STREAM_CLOSED"
        self.store.set_session(self.state, listen_key=None, now_epoch=now_epoch, reason=self.last_reason)

    def keepalive_succeeded(self, *, listen_key: str, now_epoch: float) -> UserStreamRuntimeState:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        if self.state in {SessionState.EXPIRED, SessionState.CLOSED, SessionState.BLOCKED}:
            raise PermissionError("KEEPALIVE_NOT_ALLOWED")
        self.listen_key = listen_key
        self.store.set_session(self.state, listen_key=listen_key, now_epoch=now_epoch, reason="KEEPALIVE_OK")
        return self.snapshot(now_epoch)

    def observe(self, event_or_payload: NormalizedUserEvent | Mapping[str, Any], *, now_epoch: float) -> UserEventApplyResult:
        event = event_or_payload if isinstance(event_or_payload, NormalizedUserEvent) else normalize_user_event(event_or_payload)
        if event.event_type is UserEventType.LISTEN_KEY_EXPIRED:
            self.listen_key_expired(now_epoch=now_epoch)
            return UserEventApplyResult(True, False, False, None, None, None, None, reason="LISTEN_KEY_EXPIRED")
        if self.state in {SessionState.NEW, SessionState.RECONNECTING, SessionState.RECOVERING, SessionState.BLOCKED, SessionState.EXPIRED, SessionState.CLOSED}:
            return UserEventApplyResult(False, False, False, None, None, None, None, reason="STREAM_NOT_ACTIVE")

        checkpoint = self.store.checkpoint(event)
        event_id, duplicate = self.store.append(event)
        if duplicate:
            self.last_reason = "PERSISTED_DUPLICATE"
            return UserEventApplyResult(True, True, True, None, None, None, None, reason="PERSISTED_DUPLICATE")

        if checkpoint and event.event_time_ms is not None and checkpoint.event_time_ms is not None:
            prior = (checkpoint.transaction_time_ms or -1, checkpoint.event_time_ms or -1)
            current = (event.transaction_time_ms or -1, event.event_time_ms or -1)
            if current < prior:
                self.state = SessionState.RECOVERING
                self.recovery_required = True
                self.last_recovery_cause = RecoveryCause.ORDER_EVENT_OUT_OF_ORDER
                self.last_reason = "ORDER_EVENT_OUT_OF_ORDER"
                self.store.set_session(self.state, listen_key=self.listen_key, now_epoch=now_epoch, reason=self.last_reason)
                return UserEventApplyResult(True, False, False, None, None, None, None, reason="ORDER_EVENT_OUT_OF_ORDER")

        self.last_event_time_ms = event.event_time_ms
        self._last_event_by_type[event.event_type.value] = (event.transaction_time_ms or -1, event.event_time_ms or -1)
        prior_count = checkpoint.accepted_count if checkpoint else 0
        self.store.set_checkpoint(event, prior_count + 1)
        if event.event_type is not UserEventType.ORDER_TRADE_UPDATE:
            self.last_reason = "NON_ORDER_USER_EVENT_ACCEPTED"
            return UserEventApplyResult(True, False, False, None, None, None, None, reason="NON_ORDER_USER_EVENT_ACCEPTED")

        result = self.correlation.observe(event)
        if result.reason == "UNCORRELATED_EXCHANGE_ORDER":
            self.state = SessionState.RECOVERING
            self.recovery_required = True
            self.last_recovery_cause = RecoveryCause.MANUAL
            self.last_reason = "UNCORRELATED_EXCHANGE_ORDER"
            self.store.set_session(self.state, listen_key=self.listen_key, now_epoch=now_epoch, reason=self.last_reason)
        return result

    def recover(self, assessment: RecoveryAssessment, *, now_epoch: float) -> UserStreamRuntimeState:
        if not self.recovery_required:
            raise ValueError("RECOVERY_NOT_REQUIRED")
        if assessment.safe_for_trading:
            if not self.listen_key:
                self.state = SessionState.BLOCKED
                self.last_reason = "RECOVERY_VERIFIED_WITHOUT_LISTEN_KEY"
            elif self.dispatch_reconciliation_ledger is not None:
                try:
                    self.dispatch_reconciliation_ledger.assert_recovery_closed()
                except DispatchReconciliationConflict as exc:
                    self.state = SessionState.BLOCKED
                    self.recovery_required = True
                    self.last_reason = str(exc)
                else:
                    self.state = SessionState.ACTIVE
                    self.recovery_required = False
                    self.last_reason = "RECOVERY_VERIFIED"
            else:
                self.state = SessionState.ACTIVE
                self.recovery_required = False
                self.last_reason = "RECOVERY_VERIFIED"
        else:
            self.state = SessionState.BLOCKED
            self.recovery_required = True
            self.last_reason = f"RECOVERY_FAILED:{assessment.reason}"
        self.store.set_session(self.state, listen_key=self.listen_key, now_epoch=now_epoch, reason=self.last_reason)
        return self.snapshot(now_epoch)

    def recover_with(self, recovery: UserStreamRecovery, *, now_epoch: float) -> UserStreamRuntimeState:
        assessment = recovery(self.last_recovery_cause)
        return self.recover(assessment, now_epoch=now_epoch)

    def snapshot(self, now_epoch: float) -> UserStreamRuntimeState:
        stream_health = StreamHealth.HEALTHY if self.state is SessionState.ACTIVE else StreamHealth.STALE
        if self.state is SessionState.EXPIRED:
            stream_health = StreamHealth.EXPIRED
        elif self.state in {SessionState.RECOVERING, SessionState.RECONNECTING, SessionState.BLOCKED}:
            stream_health = StreamHealth.GAP_SUSPECTED
        trading_allowed = self.state is SessionState.ACTIVE and not self.recovery_required and stream_health is StreamHealth.HEALTHY
        if self.last_event_time_ms is not None and self.state is SessionState.ACTIVE:
            age = now_epoch - self.last_event_time_ms / 1000.0
            if age > self.policy.stale_after_seconds:
                stream_health = StreamHealth.STALE
                trading_allowed = False
        return UserStreamRuntimeState(
            state=self.state,
            stream_health=stream_health,
            listen_key_present=bool(self.listen_key),
            trading_allowed=trading_allowed,
            recovery_required=self.recovery_required,
            last_event_time_ms=self.last_event_time_ms,
            reason=self.last_reason,
        )

    def require_trading_allowed(self, now_epoch: float) -> None:
        state = self.snapshot(now_epoch)
        if not state.trading_allowed:
            raise PermissionError("USER_STREAM_TRADING_BLOCKED")

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


class CorrelationConflict(ValueError):
    pass


class CorrelationNotFound(ValueError):
    pass


@dataclass(frozen=True)
class CorrelationRecord:
    intent_id: str
    order_request_id: str | None
    client_order_id: str
    exchange_order_id: str | None
    created_at_epoch: float
    updated_at_epoch: float


@dataclass(frozen=True)
class EventJournalRecord:
    event_id: str
    intent_id: str | None
    client_order_id: str | None
    exchange_order_id: str | None
    event_type: str
    raw_hash: str
    observed_at_epoch: float
    payload: Mapping[str, Any]


class DurableExecutionCorrelationStore:
    """Durable correlation/journal boundary for restart-safe execution recovery.

    The store persists only execution metadata and evidence. Runtime credentials and
    transport/socket objects are intentionally excluded. All mappings are unique in both
    directions and updates are transactional so a process restart cannot create a partial
    correlation.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS correlations ("
            "intent_id TEXT PRIMARY KEY, order_request_id TEXT, client_order_id TEXT NOT NULL UNIQUE, "
            "exchange_order_id TEXT UNIQUE, created_at_epoch REAL NOT NULL, updated_at_epoch REAL NOT NULL)"
        )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_corr_exchange ON correlations(exchange_order_id) "
            "WHERE exchange_order_id IS NOT NULL"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS event_journal ("
            "event_id TEXT PRIMARY KEY, intent_id TEXT, client_order_id TEXT, exchange_order_id TEXT, "
            "event_type TEXT NOT NULL, raw_hash TEXT NOT NULL, observed_at_epoch REAL NOT NULL, payload_json TEXT NOT NULL)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_event_client ON event_journal(client_order_id)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_event_exchange ON event_journal(exchange_order_id)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_event_intent ON event_journal(intent_id)")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def register(self, *, intent_id: str, order_request_id: str | None,
                 client_order_id: str, now_epoch: float) -> CorrelationRecord:
        if not intent_id:
            raise ValueError("INTENT_ID_REQUIRED")
        if not client_order_id:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        existing = self._db.execute(
            "SELECT intent_id,order_request_id,client_order_id,exchange_order_id,created_at_epoch,updated_at_epoch "
            "FROM correlations WHERE intent_id=? OR client_order_id=?",
            (intent_id, client_order_id),
        ).fetchone()
        if existing:
            current = CorrelationRecord(*existing)
            if current.intent_id != intent_id or current.client_order_id != client_order_id:
                raise CorrelationConflict("CLIENT_OR_INTENT_CORRELATION_CONFLICT")
            if order_request_id is not None and current.order_request_id not in (None, order_request_id):
                raise CorrelationConflict("ORDER_REQUEST_CORRELATION_CONFLICT")
            self._db.execute(
                "UPDATE correlations SET order_request_id=COALESCE(order_request_id,?),updated_at_epoch=? WHERE intent_id=?",
                (order_request_id, float(now_epoch), intent_id),
            )
            self._db.commit()
            return self.get_by_intent(intent_id)
        self._db.execute(
            "INSERT INTO correlations(intent_id,order_request_id,client_order_id,exchange_order_id,created_at_epoch,updated_at_epoch) "
            "VALUES(?,?,?,?,?,?)",
            (intent_id, order_request_id, client_order_id, None, float(now_epoch), float(now_epoch)),
        )
        self._db.commit()
        return self.get_by_intent(intent_id)

    def bind_exchange(self, *, intent_id: str, exchange_order_id: str, now_epoch: float) -> CorrelationRecord:
        if not exchange_order_id:
            raise ValueError("EXCHANGE_ORDER_ID_REQUIRED")
        current = self.get_by_intent(intent_id)
        prior = self._db.execute(
            "SELECT intent_id FROM correlations WHERE exchange_order_id=?", (exchange_order_id,)
        ).fetchone()
        if prior and prior[0] != intent_id:
            raise CorrelationConflict("EXCHANGE_ORDER_ID_CORRELATION_CONFLICT")
        if current.exchange_order_id not in (None, exchange_order_id):
            raise CorrelationConflict("EXCHANGE_ORDER_ID_REBIND_CONFLICT")
        self._db.execute(
            "UPDATE correlations SET exchange_order_id=?,updated_at_epoch=? WHERE intent_id=?",
            (exchange_order_id, float(now_epoch), intent_id),
        )
        self._db.commit()
        return self.get_by_intent(intent_id)

    def get_by_intent(self, intent_id: str) -> CorrelationRecord:
        row = self._db.execute(
            "SELECT intent_id,order_request_id,client_order_id,exchange_order_id,created_at_epoch,updated_at_epoch "
            "FROM correlations WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row is None:
            raise CorrelationNotFound("CORRELATION_NOT_FOUND")
        return CorrelationRecord(*row)

    def get_by_client(self, client_order_id: str) -> CorrelationRecord | None:
        row = self._db.execute(
            "SELECT intent_id,order_request_id,client_order_id,exchange_order_id,created_at_epoch,updated_at_epoch "
            "FROM correlations WHERE client_order_id=?", (client_order_id,)
        ).fetchone()
        return CorrelationRecord(*row) if row else None

    def get_by_exchange(self, exchange_order_id: str) -> CorrelationRecord | None:
        row = self._db.execute(
            "SELECT intent_id,order_request_id,client_order_id,exchange_order_id,created_at_epoch,updated_at_epoch "
            "FROM correlations WHERE exchange_order_id=?", (exchange_order_id,)
        ).fetchone()
        return CorrelationRecord(*row) if row else None

    def correlate(self, *, client_order_id: str | None, exchange_order_id: str | None) -> CorrelationRecord | None:
        by_client = self.get_by_client(client_order_id) if client_order_id else None
        by_exchange = self.get_by_exchange(exchange_order_id) if exchange_order_id else None
        if by_client and by_exchange and by_client.intent_id != by_exchange.intent_id:
            raise CorrelationConflict("ORDER_CORRELATION_CONFLICT")
        return by_client or by_exchange

    @staticmethod
    def _payload_hash(payload: Mapping[str, Any]) -> str:
        import hashlib
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def append_event(self, *, event_id: str, intent_id: str | None,
                     client_order_id: str | None, exchange_order_id: str | None,
                     event_type: str, raw_hash: str, observed_at_epoch: float,
                     payload: Mapping[str, Any]) -> bool:
        """Append idempotently. Returns True only for a newly persisted event."""
        if not event_id:
            raise ValueError("EVENT_ID_REQUIRED")
        if not event_type:
            raise ValueError("EVENT_TYPE_REQUIRED")
        if not raw_hash:
            raw_hash = self._payload_hash(payload)
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        cur = self._db.execute(
            "INSERT OR IGNORE INTO event_journal(event_id,intent_id,client_order_id,exchange_order_id,event_type,raw_hash,observed_at_epoch,payload_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (event_id, intent_id, client_order_id, exchange_order_id, event_type, raw_hash, float(observed_at_epoch), payload_json),
        )
        self._db.commit()
        return cur.rowcount == 1

    def events_for_intent(self, intent_id: str) -> tuple[EventJournalRecord, ...]:
        rows = self._db.execute(
            "SELECT event_id,intent_id,client_order_id,exchange_order_id,event_type,raw_hash,observed_at_epoch,payload_json "
            "FROM event_journal WHERE intent_id=? ORDER BY observed_at_epoch,event_id", (intent_id,)
        ).fetchall()
        return tuple(EventJournalRecord(r[0], r[1], r[2], r[3], r[4], r[5], float(r[6]), json.loads(r[7])) for r in rows)

    def count_events(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM event_journal").fetchone()[0])


class RestartSafeCorrelation:
    """In-memory cache backed by DurableExecutionCorrelationStore.

    A caller can reconstruct the object after restart and continue correlating without
    re-registering exchange IDs or losing the event journal.
    """

    def __init__(self, store: DurableExecutionCorrelationStore) -> None:
        self.store = store

    def register(self, *, intent_id: str, order_request_id: str | None,
                 client_order_id: str, now_epoch: float) -> CorrelationRecord:
        return self.store.register(intent_id=intent_id, order_request_id=order_request_id,
                                   client_order_id=client_order_id, now_epoch=now_epoch)

    def bind_exchange(self, *, intent_id: str, exchange_order_id: str, now_epoch: float) -> CorrelationRecord:
        return self.store.bind_exchange(intent_id=intent_id, exchange_order_id=exchange_order_id, now_epoch=now_epoch)

    def correlate(self, *, client_order_id: str | None, exchange_order_id: str | None) -> CorrelationRecord | None:
        return self.store.correlate(client_order_id=client_order_id, exchange_order_id=exchange_order_id)

    def journal(self, *, event_id: str, record: CorrelationRecord | None,
                event_type: str, raw_hash: str, observed_at_epoch: float,
                payload: Mapping[str, Any]) -> bool:
        return self.store.append_event(
            event_id=event_id,
            intent_id=record.intent_id if record else None,
            client_order_id=record.client_order_id if record else None,
            exchange_order_id=record.exchange_order_id if record else None,
            event_type=event_type,
            raw_hash=raw_hash,
            observed_at_epoch=observed_at_epoch,
            payload=payload,
        )

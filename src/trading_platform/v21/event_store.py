from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json, sqlite3
from typing import Any, Iterable, Mapping


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sha256_json(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    sequence: int
    occurred_at_ms: int
    event_type: str
    aggregate_id: str
    payload: Mapping[str, Any]
    prev_hash: str
    event_hash: str


@dataclass(frozen=True)
class AppendResult:
    event: LedgerEvent
    duplicate: bool


class EventStore:
    """Durable append-only event store with hash chaining and idempotent event IDs."""
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""
        CREATE TABLE IF NOT EXISTS events(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            occurred_at_ms INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        )""")
        self._db.execute("""
        CREATE TRIGGER IF NOT EXISTS deny_event_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_UPDATE_FORBIDDEN');
        END;
        """)
        self._db.execute("""
        CREATE TRIGGER IF NOT EXISTS deny_event_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_DELETE_FORBIDDEN');
        END;
        """)
        self._db.commit()

    def append(self, *, event_id: str, occurred_at_ms: int, event_type: str,
               aggregate_id: str, payload: Mapping[str, Any]) -> AppendResult:
        existing = self._db.execute(
            "SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if existing:
            event = self._row_to_event(existing)
            candidate = self._compute_hash(event.sequence, event.event_id, event.occurred_at_ms,
                                           event.event_type, event.aggregate_id, event.payload, event.prev_hash)
            if candidate != event.event_hash:
                raise RuntimeError("EVENT_STORE_CORRUPTED")
            return AppendResult(event, True)

        row = self._db.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        sequence = (int(row[0]) + 1) if row else 1
        prev_hash = str(row[1]) if row else "GENESIS"
        event_hash = self._compute_hash(sequence, event_id, occurred_at_ms, event_type, aggregate_id, payload, prev_hash)
        try:
            self._db.execute(
                "INSERT INTO events(sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                (sequence, event_id, occurred_at_ms, event_type, aggregate_id, canonical_json(payload).decode(), prev_hash, event_hash),
            )
            self._db.commit()
        except sqlite3.IntegrityError as exc:
            self._db.rollback()
            raise RuntimeError("EVENT_APPEND_CONFLICT") from exc
        event = LedgerEvent(event_id, sequence, occurred_at_ms, event_type, aggregate_id, dict(payload), prev_hash, event_hash)
        return AppendResult(event, False)

    def append_exclusive(
        self,
        *,
        event_id: str,
        occurred_at_ms: int,
        event_type: str,
        aggregate_id: str,
        payload: Mapping[str, Any],
        exclusive_event_types: Iterable[str],
    ) -> AppendResult:
        """Append exactly one terminal event for an aggregate under a writer lock.

        The caller supplies event types that are mutually exclusive for the aggregate.
        The check and append happen in one SQLite ``BEGIN IMMEDIATE`` transaction, so
        two independent connections cannot both observe the aggregate as non-terminal
        and then append conflicting terminal transitions. Existing identical ``event_id``
        requests are idempotent; a different terminal event is rejected.
        """
        exclusive = tuple(str(v) for v in exclusive_event_types)
        if not exclusive:
            raise ValueError("EXCLUSIVE_EVENT_TYPES_REQUIRED")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                "SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash "
                "FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing:
                event = self._row_to_event(existing)
                candidate = self._compute_hash(
                    event.sequence, event.event_id, event.occurred_at_ms, event.event_type,
                    event.aggregate_id, event.payload, event.prev_hash,
                )
                if (
                    candidate != event.event_hash
                    or event.event_type != str(event_type)
                    or event.aggregate_id != str(aggregate_id)
                    or event.occurred_at_ms != int(occurred_at_ms)
                    or dict(event.payload) != dict(payload)
                ):
                    raise RuntimeError("EVENT_APPEND_CONFLICT")
                self._db.rollback()
                return AppendResult(event, True)

            placeholders = ",".join("?" for _ in exclusive)
            row = self._db.execute(
                f"SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash "
                f"FROM events WHERE aggregate_id=? AND event_type IN ({placeholders}) "
                "ORDER BY sequence LIMIT 1",
                (aggregate_id, *exclusive),
            ).fetchone()
            if row is not None:
                prior = self._row_to_event(row)
                self._db.rollback()
                raise RuntimeError(f"EXCLUSIVE_AGGREGATE_TERMINAL:{prior.event_type}")

            row = self._db.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence = (int(row[0]) + 1) if row else 1
            prev_hash = str(row[1]) if row else "GENESIS"
            payload = dict(payload)
            event_hash = self._compute_hash(sequence, event_id, occurred_at_ms, event_type, aggregate_id, payload, prev_hash)
            self._db.execute(
                "INSERT INTO events(sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                (sequence, event_id, occurred_at_ms, event_type, aggregate_id, canonical_json(payload).decode(), prev_hash, event_hash),
            )
            self._db.commit()
            return AppendResult(
                LedgerEvent(event_id, sequence, occurred_at_ms, event_type, aggregate_id, payload, prev_hash, event_hash),
                False,
            )
        except Exception:
            self._db.rollback()
            raise

    def append_atomic(self, events: Iterable[Mapping[str, Any]]) -> tuple[LedgerEvent, ...]:
        """Append a non-empty batch in one SQLite transaction.

        The batch is either fully durable or not visible at all. A partial pre-existing
        batch is rejected because it would violate atomic version/audit creation.
        """
        specs = tuple(dict(event) for event in events)
        if not specs:
            raise ValueError("ATOMIC_EVENT_BATCH_EMPTY")
        ids = [str(spec["event_id"]) for spec in specs]
        if len(set(ids)) != len(ids):
            raise ValueError("ATOMIC_EVENT_BATCH_DUPLICATE_ID")

        existing_rows = {}
        for event_id in ids:
            row = self._db.execute(
                "SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash "
                "FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is not None:
                existing_rows[event_id] = self._row_to_event(row)
        if existing_rows:
            if len(existing_rows) != len(ids):
                raise RuntimeError("EVENT_APPEND_PARTIAL_BATCH")
            results = []
            for spec in specs:
                event = existing_rows[str(spec["event_id"]) ]
                candidate = self._compute_hash(
                    event.sequence, event.event_id, event.occurred_at_ms, event.event_type,
                    event.aggregate_id, event.payload, event.prev_hash,
                )
                if candidate != event.event_hash or event.event_type != str(spec["event_type"]) \
                   or event.aggregate_id != str(spec["aggregate_id"]) \
                   or event.occurred_at_ms != int(spec["occurred_at_ms"]) \
                   or dict(event.payload) != dict(spec["payload"]):
                    raise RuntimeError("EVENT_APPEND_CONFLICT")
                results.append(event)
            return tuple(results)

        row = self._db.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        sequence = (int(row[0]) + 1) if row else 1
        prev_hash = str(row[1]) if row else "GENESIS"
        built = []
        try:
            for spec in specs:
                event_id = str(spec["event_id"])
                occurred_at_ms = int(spec["occurred_at_ms"])
                event_type = str(spec["event_type"])
                aggregate_id = str(spec["aggregate_id"])
                payload = dict(spec["payload"])
                event_hash = self._compute_hash(sequence, event_id, occurred_at_ms, event_type, aggregate_id, payload, prev_hash)
                self._db.execute(
                    "INSERT INTO events(sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                    (sequence, event_id, occurred_at_ms, event_type, aggregate_id, canonical_json(payload).decode(), prev_hash, event_hash),
                )
                built.append(LedgerEvent(event_id, sequence, occurred_at_ms, event_type, aggregate_id, payload, prev_hash, event_hash))
                prev_hash = event_hash
                sequence += 1
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return tuple(built)

    def iter_events(self, *, start_sequence: int = 1) -> Iterable[LedgerEvent]:
        rows = self._db.execute(
            "SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash FROM events WHERE sequence>=? ORDER BY sequence",
            (start_sequence,),
        )
        for row in rows:
            yield self._row_to_event(row)

    def get(self, event_id: str) -> LedgerEvent | None:
        row = self._db.execute(
            "SELECT sequence,event_id,occurred_at_ms,event_type,aggregate_id,payload_json,prev_hash,event_hash FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return self._row_to_event(row) if row else None

    def verify_chain(self) -> bool:
        previous = "GENESIS"
        expected_sequence = 1
        for event in self.iter_events():
            if event.sequence != expected_sequence or event.prev_hash != previous:
                return False
            raw = json.loads(json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str))
            computed = self._compute_hash(event.sequence, event.event_id, event.occurred_at_ms,
                                          event.event_type, event.aggregate_id, raw, event.prev_hash)
            if computed != event.event_hash:
                return False
            previous = event.event_hash
            expected_sequence += 1
        return True

    def latest_sequence(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()
        return int(row[0])

    @staticmethod
    def _compute_hash(sequence: int, event_id: str, occurred_at_ms: int, event_type: str,
                      aggregate_id: str, payload: Mapping[str, Any], prev_hash: str) -> str:
        body = {
            "sequence": sequence, "event_id": event_id, "occurred_at_ms": occurred_at_ms,
            "event_type": event_type, "aggregate_id": aggregate_id,
            "payload": json.loads(canonical_json(payload)), "prev_hash": prev_hash,
        }
        return sha256_json(body)

    @staticmethod
    def _row_to_event(row: tuple[Any, ...]) -> LedgerEvent:
        seq, eid, ts, typ, agg, payload_json, prev, h = row
        return LedgerEvent(str(eid), int(seq), int(ts), str(typ), str(agg), json.loads(payload_json), str(prev), str(h))

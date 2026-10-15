from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore


class ImmutableRecordError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImmutableRecord:
    record_id: str
    version: int
    payload: Mapping[str, Any]
    audit_id: str
    created_at_ms: int
    supersedes_record_id: str | None = None

    @property
    def fingerprint(self) -> str:
        body = {
            "record_id": self.record_id,
            "version": self.version,
            "payload": self.payload,
            "audit_id": self.audit_id,
            "created_at_ms": self.created_at_ms,
            "supersedes_record_id": self.supersedes_record_id,
        }
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ImmutableRecordAuthority:
    """Append-only authority for records whose mutation requires version + audit.

    No existing version is updated or deleted. A change is represented by a new
    versioned record and a separate immutable audit event that links the two.
    """

    RECORD_CREATED = "IMMUTABLE_RECORD_CREATED"
    RECORD_SUPERSEDED = "IMMUTABLE_RECORD_SUPERSEDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def create(
        self,
        *,
        record_id: str,
        payload: Mapping[str, Any],
        audit_id: str,
        created_at_ms: int,
    ) -> ImmutableRecord:
        if not record_id or not audit_id:
            raise ValueError("IMMUTABLE_RECORD_ID_AND_AUDIT_REQUIRED")
        record = ImmutableRecord(record_id, 1, dict(payload), audit_id, int(created_at_ms))
        self._append_record(record, event_type=self.RECORD_CREATED)
        return record

    def supersede(
        self,
        *,
        previous_record_id: str,
        new_record_id: str,
        payload: Mapping[str, Any],
        audit_id: str,
        created_at_ms: int,
    ) -> ImmutableRecord:
        previous = self.get(previous_record_id)
        if previous is None:
            raise ImmutableRecordError("IMMUTABLE_RECORD_PREVIOUS_NOT_FOUND")
        if not new_record_id or not audit_id:
            raise ValueError("IMMUTABLE_RECORD_ID_AND_AUDIT_REQUIRED")
        if new_record_id == previous_record_id:
            raise ImmutableRecordError("IMMUTABLE_RECORD_UPDATE_FORBIDDEN")
        record = ImmutableRecord(
            new_record_id,
            previous.version + 1,
            dict(payload),
            audit_id,
            int(created_at_ms),
            supersedes_record_id=previous.record_id,
        )
        self._append_record(record, event_type=self.RECORD_SUPERSEDED)
        return record

    def get(self, record_id: str) -> ImmutableRecord | None:
        event = self.store.get(f"immutable:record:{record_id}")
        if event is None:
            return None
        return self._from_event(event.payload)

    def assert_chain_valid(self, record_id: str) -> ImmutableRecord:
        record = self.get(record_id)
        if record is None:
            raise ImmutableRecordError("IMMUTABLE_RECORD_NOT_FOUND")
        if not self.store.verify_chain():
            raise ImmutableRecordError("IMMUTABLE_RECORD_AUDIT_CHAIN_INVALID")
        if record.supersedes_record_id is not None:
            previous = self.get(record.supersedes_record_id)
            if previous is None or record.version != previous.version + 1:
                raise ImmutableRecordError("IMMUTABLE_RECORD_VERSION_CHAIN_INVALID")
            audit = self.store.get(f"immutable:audit:{record.audit_id}")
            if audit is None:
                raise ImmutableRecordError("IMMUTABLE_RECORD_AUDIT_MISSING")
        return record

    def _append_record(self, record: ImmutableRecord, *, event_type: str) -> None:
        record_event = {
            "event_id": f"immutable:record:{record.record_id}",
            "occurred_at_ms": record.created_at_ms,
            "event_type": event_type,
            "aggregate_id": record.record_id,
            "payload": {
                "record_id": record.record_id,
                "version": record.version,
                "payload": dict(record.payload),
                "audit_id": record.audit_id,
                "created_at_ms": record.created_at_ms,
                "supersedes_record_id": record.supersedes_record_id,
            },
        }
        audit_event = {
            "event_id": f"immutable:audit:{record.audit_id}",
            "occurred_at_ms": record.created_at_ms,
            "event_type": "IMMUTABLE_RECORD_AUDIT",
            "aggregate_id": record.record_id,
            "payload": {
                "audit_id": record.audit_id,
                "previous_record_id": record.supersedes_record_id,
                "new_record_id": record.record_id,
                "new_version": record.version,
                "previous_version": (record.version - 1 if record.supersedes_record_id is not None else None),
            },
        }
        self.store.append_atomic((record_event, audit_event))

    @staticmethod
    def _from_event(payload: Mapping[str, Any]) -> ImmutableRecord:
        return ImmutableRecord(
            record_id=str(payload["record_id"]),
            version=int(payload["version"]),
            payload=dict(payload["payload"]),
            audit_id=str(payload["audit_id"]),
            created_at_ms=int(payload["created_at_ms"]),
            supersedes_record_id=(str(payload["supersedes_record_id"]) if payload.get("supersedes_record_id") else None),
        )

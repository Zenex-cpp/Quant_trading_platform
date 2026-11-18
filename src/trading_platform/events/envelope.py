from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import EventSchemaRegistry


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    event_version: str
    schema_version: str
    event_time: datetime
    receive_time: datetime
    processing_time: datetime
    source: str
    correlation_id: str | None = None
    sequence_number: int | None = None

    def validate(self) -> None:
        for field_name in ("event_id", "event_type", "event_version", "schema_version", "source"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"EVENT_ENVELOPE_FIELD_REQUIRED:{field_name}")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str) or not self.correlation_id.strip()
        ):
            raise ValueError("EVENT_ENVELOPE_FIELD_INVALID:correlation_id")

        times = (self.event_time, self.receive_time, self.processing_time)
        if any(not isinstance(value, datetime) for value in times):
            raise ValueError("EVENT_TIME_REQUIRED")
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("EVENT_TIMEZONE_REQUIRED")
        if self.receive_time < self.event_time:
            raise ValueError("RECEIVE_BEFORE_EVENT_TIME")
        if self.processing_time < self.receive_time:
            raise ValueError("PROCESSING_BEFORE_RECEIVE_TIME")

        if self.sequence_number is not None and (
            isinstance(self.sequence_number, bool)
            or not isinstance(self.sequence_number, int)
            or self.sequence_number < 0
        ):
            raise ValueError("EVENT_SEQUENCE_NUMBER_INVALID")


@dataclass(frozen=True)
class Event:
    envelope: EventEnvelope
    payload: Any

    def validate(self, registry: EventSchemaRegistry) -> None:
        registry.validate_event(self)

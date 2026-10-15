from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
    correlation_id: str
    sequence_number: int | None = None

@dataclass(frozen=True)
class Event:
    envelope: EventEnvelope
    payload: Any

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Any

class DeliverySemantics(str, Enum):
    AT_LEAST_ONCE = "AT_LEAST_ONCE"
    AT_MOST_ONCE = "AT_MOST_ONCE"
    UNKNOWN = "UNKNOWN"

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
    correlation_id: str | None
    sequence_number: int | None

    def validate(self) -> None:
        for value in (self.event_time, self.receive_time, self.processing_time):
            if value.tzinfo is None:
                raise ValueError("EVENT_TIMEZONE_REQUIRED")
        if self.receive_time < self.event_time:
            raise ValueError("RECEIVE_BEFORE_EVENT_TIME")
        if self.processing_time < self.receive_time:
            raise ValueError("PROCESSING_BEFORE_RECEIVE_TIME")

@dataclass(frozen=True)
class MarketEvent:
    envelope: EventEnvelope
    payload: dict[str, Any]
    delivery_semantics: DeliverySemantics

    def validate(self) -> None:
        self.envelope.validate()
        if not self.payload:
            raise ValueError("EMPTY_MARKET_PAYLOAD")

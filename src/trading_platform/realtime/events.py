from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

from trading_platform.events.envelope import EventEnvelope

class DeliverySemantics(str, Enum):
    AT_LEAST_ONCE = "AT_LEAST_ONCE"
    AT_MOST_ONCE = "AT_MOST_ONCE"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class MarketEvent:
    envelope: EventEnvelope
    payload: dict[str, Any]
    delivery_semantics: DeliverySemantics

    def validate(self) -> None:
        self.envelope.validate()
        if not self.payload:
            raise ValueError("EMPTY_MARKET_PAYLOAD")

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta, timezone
from typing import Protocol

class ConnectionState(str, Enum):
    DISCONNECTED="DISCONNECTED"
    CONNECTING="CONNECTING"
    CONNECTED="CONNECTED"
    DEGRADED="DEGRADED"
    RECOVERING="RECOVERING"
    HALTED="HALTED"

@dataclass(frozen=True)
class RateLimitBudget:
    capacity: int
    used: int
    window_seconds: int
    window_started_at: datetime
    def remaining(self) -> int:
        return max(0, self.capacity-self.used)
    def reserve(self, weight: int) -> "RateLimitBudget":
        if weight <= 0: raise ValueError("INVALID_RATE_LIMIT_WEIGHT")
        if weight > self.remaining(): raise ValueError("RATE_LIMIT_EXCEEDED")
        return RateLimitBudget(self.capacity, self.used+weight, self.window_seconds, self.window_started_at)

class VenueAdapterContract(Protocol):
    venue: str
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def subscribe_market(self, streams: list[str]) -> None: ...
    def subscribe_user(self) -> None: ...
    def reconnect(self) -> None: ...
    def reconcile(self) -> None: ...
    def state(self) -> ConnectionState: ...

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

class ClockHealth(str, Enum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"

@dataclass(frozen=True)
class ClockIntegrity:
    source_time: datetime
    wall_clock: datetime
    monotonic_elapsed_ms: int
    ntp_offset_ms: int
    max_allowed_offset_ms: int
    health: ClockHealth
    def validate(self) -> None:
        if self.source_time.tzinfo is None or self.wall_clock.tzinfo is None:
            raise ValueError("CLOCK_TIMEZONE_REQUIRED")
        if self.monotonic_elapsed_ms < 0:
            raise ValueError("NEGATIVE_MONOTONIC_ELAPSED")
        if self.max_allowed_offset_ms < 0:
            raise ValueError("INVALID_CLOCK_THRESHOLD")

def check_clock_integrity(*, source_time: datetime, wall_clock: datetime, ntp_offset_ms: int, max_allowed_offset_ms: int) -> ClockIntegrity:
    obj = ClockIntegrity(source_time, wall_clock, 0, ntp_offset_ms, max_allowed_offset_ms,
                         ClockHealth.VALID if abs(ntp_offset_ms) <= max_allowed_offset_ms else ClockHealth.INVALID)
    obj.validate()
    return obj

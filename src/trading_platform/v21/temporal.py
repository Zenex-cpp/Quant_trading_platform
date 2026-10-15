from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class TemporalState(str, Enum):
    CONTIGUOUS="CONTIGUOUS"
    GAP_SUSPECTED="GAP_SUSPECTED"
    RECOVERY_REQUIRED="RECOVERY_REQUIRED"

@dataclass(frozen=True)
class TemporalGap:
    expected_sequence: int
    observed_sequence: int
    reason: str

class TemporalIntegrity:
    def __init__(self) -> None:
        self.expected_sequence = 1
        self.state = TemporalState.CONTIGUOUS
        self.gaps: list[TemporalGap] = []

    def observe(self, sequence: int) -> TemporalState:
        if sequence != self.expected_sequence:
            self.gaps.append(TemporalGap(self.expected_sequence, sequence, "NON_CONTIGUOUS_SEQUENCE"))
            self.state = TemporalState.GAP_SUSPECTED
            self.expected_sequence = max(self.expected_sequence, sequence + 1)
            return self.state
        self.expected_sequence += 1
        return self.state

    def require_recovery(self) -> None:
        if self.state is TemporalState.GAP_SUSPECTED:
            self.state = TemporalState.RECOVERY_REQUIRED
            return
        raise RuntimeError("NO_GAP_TO_RECOVER")

    def recovered(self) -> None:
        if self.state is not TemporalState.RECOVERY_REQUIRED:
            raise RuntimeError("RECOVERY_NOT_REQUIRED")
        self.state = TemporalState.CONTIGUOUS
        self.gaps.clear()

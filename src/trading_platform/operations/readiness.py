from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class ReadinessStatus(str, Enum):
    BLOCKED="BLOCKED"
    READY_FOR_SHADOW="READY_FOR_SHADOW"
    READY_FOR_CANARY="READY_FOR_CANARY"
    READY_FOR_LIVE="READY_FOR_LIVE"

@dataclass(frozen=True)
class OperationalReadiness:
    data_validation: bool
    invariants: bool
    state_matrix: bool
    risk_engine: bool
    kill_switch: bool
    reconciliation: bool
    accounting: bool
    execution_realistic: bool
    monitoring: bool
    security: bool
    permissions: bool
    network_isolation: bool
    backup_restore: bool
    rollback_tested: bool
    failure_injection: bool
    recovery_proof: bool
    evidence_snapshot: bool
    promotion_bundle: bool
    approval: bool
    def status(self)->ReadinessStatus:
        if not all(self.__dict__.values()): return ReadinessStatus.BLOCKED
        return ReadinessStatus.READY_FOR_LIVE

@dataclass(frozen=True)
class KillSwitch:
    activated: bool
    activated_at: datetime | None
    reason: str | None
    actor: str | None

def activation_blocked_by_kill(kill: KillSwitch)->bool:
    return kill.activated

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class DRStatus(str, Enum): READY='READY'; BLOCKED='BLOCKED'; NOT_VERIFIED='NOT_VERIFIED'

@dataclass(frozen=True)
class DRContract:
    contract_id: str
    rpo_seconds: int
    rto_seconds: int
    backup_frequency_seconds: int
    restore_test_frequency_seconds: int
    status: DRStatus = DRStatus.NOT_VERIFIED

    def validate(self) -> None:
        if min(self.rpo_seconds,self.rto_seconds,self.backup_frequency_seconds,self.restore_test_frequency_seconds) < 0:
            raise ValueError('NEGATIVE_DR_PARAMETER')
        if self.backup_frequency_seconds > self.rpo_seconds and self.rpo_seconds >= 0:
            raise ValueError('BACKUP_FREQUENCY_EXCEEDS_RPO')

@dataclass(frozen=True)
class RecoveryProof:
    state_reconciled: bool
    invariants_pass: bool
    no_unresolved_critical_issue: bool
    guards_pass: bool

    @property
    def verified(self) -> bool:
        return self.state_reconciled and self.invariants_pass and self.no_unresolved_critical_issue and self.guards_pass

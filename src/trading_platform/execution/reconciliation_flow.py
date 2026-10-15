from dataclasses import dataclass
from enum import Enum

class ReconciliationTrigger(str, Enum): STARTUP='STARTUP'; PRE_TRADE='PRE_TRADE'; POST_TRADE='POST_TRADE'; POST_RESTART='POST_RESTART'; EVENT_DRIVEN='EVENT_DRIVEN'; SCHEDULED='SCHEDULED'

@dataclass(frozen=True)
class ReconciliationResult:
    case_id:str
    matched:bool
    state_reconciled:bool
    invariants_pass:bool
    no_unresolved_critical_issue:bool
    guards_pass:bool
    classification:str

    @property
    def recovery_verified(self)->bool:
        return self.state_reconciled and self.invariants_pass and self.no_unresolved_critical_issue and self.guards_pass

def recovery_from_result(r:ReconciliationResult)->bool:
    return r.recovery_verified

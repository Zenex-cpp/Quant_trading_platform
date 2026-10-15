from dataclasses import dataclass
from enum import Enum

class AccountingState(str, Enum):
    UNRECONCILED="UNRECONCILED"
    RECONCILED="RECONCILED"
    ADJUSTED="ADJUSTED"
    UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class ReconciliationCase:
    case_id: str
    severity: str
    status: str
    owner: str
    remediation: str
    closure_evidence: str | None=None

def assert_recovery_proof(*, state_reconciled: bool, invariants_pass: bool, no_unresolved_critical_issue: bool, guards_pass: bool) -> bool:
    return state_reconciled and invariants_pass and no_unresolved_critical_issue and guards_pass

from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class StoppingEvidence:
    diminishing_returns: bool
    repeated_variants: bool
    excessive_data_mining: bool
    budget_exhausted: bool
    no_incremental_information: bool

def should_stop(x: StoppingEvidence) -> tuple[bool, str]:
    if x.budget_exhausted: return True, 'BUDGET_EXHAUSTED'
    if x.excessive_data_mining: return True, 'EXCESSIVE_DATA_MINING'
    if x.no_incremental_information: return True, 'NO_INCREMENTAL_INFORMATION'
    if x.diminishing_returns and x.repeated_variants: return True, 'DIMINISHING_RETURNS'
    return False, 'CONTINUE'

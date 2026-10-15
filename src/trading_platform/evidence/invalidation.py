from __future__ import annotations
from dataclasses import dataclass
from .graph import Evidence, EvidenceState

@dataclass(frozen=True)
class InvalidationEvent:
    incident_id: str
    changed_dependency: str
    prior_state: EvidenceState
    new_state: EvidenceState
    affected_evidence: tuple[str,...]
    affected_gates: tuple[str,...]
    reason: str

def suspend(evidence: Evidence, incident_id: str, affected: tuple[str,...], gates: tuple[str,...], reason: str) -> InvalidationEvent:
    if evidence.state not in {EvidenceState.VALID, EvidenceState.REVALIDATED}: raise ValueError('EVIDENCE_NOT_SUSPENDABLE')
    return InvalidationEvent(incident_id,evidence.evidence_id,evidence.state,EvidenceState.SUSPENDED,affected,gates,reason)

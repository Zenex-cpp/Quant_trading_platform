from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class GateResult(str, Enum):
    PASS='PASS'; WARNING='WARNING'; FAIL='FAIL'

@dataclass(frozen=True)
class Gate:
    gate_id: str
    candidate_version: str
    run_id: str
    input_versions: tuple[str,...]
    checks: tuple[str,...]
    result: GateResult
    required_artifacts: tuple[str,...]
    evidence_refs: tuple[str,...]
    owner: str
    reviewer: str | None
    timestamp: str
    expiration: str | None
    revalidation_condition: str

@dataclass(frozen=True)
class GateInvalidation:
    gate_id: str
    reason: str
    changed_dependencies: tuple[str,...]
    rerun_required: bool

def invalidate_gate(gate: Gate, changed_dependencies: tuple[str,...]) -> GateInvalidation:
    impacted = tuple(x for x in changed_dependencies if x in gate.input_versions or x in gate.evidence_refs or x in gate.required_artifacts)
    return GateInvalidation(gate.gate_id, 'DEPENDENCY_CHANGED', impacted, bool(impacted))

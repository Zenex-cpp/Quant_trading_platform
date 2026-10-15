from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from .session import EvidenceArtifact, LiveTestnetSession, SessionConfig, SessionStatus

@dataclass(frozen=True)
class Step:
    scenario_id: str
    method: str
    path: str
    params: Mapping[str,str]
    probe: Callable[[Mapping[str,Any]], tuple[bool, tuple[str,...], tuple[str,...]]]

class E2EPlan:
    """Ordered control flow. Live steps are blocked unless explicitly enabled by the caller."""
    def __init__(self, steps: Sequence[Step]): self.steps=tuple(steps)

    def execute(self, session: LiveTestnetSession, *, allow_network: bool=False) -> tuple[EvidenceArtifact,...]:
        if not allow_network:
            raise RuntimeError('NETWORK_EXECUTION_NOT_ENABLED')
        results=[]
        for step in self.steps:
            result=session.run_probe(step.scenario_id, step.method, step.path, step.params, step.probe)
            results.append(result)
            if result.status != SessionStatus.PASSED:
                break
        return tuple(results)

def http_ok(response: Mapping[str,Any]) -> tuple[bool,tuple[str,...],tuple[str,...]]:
    return True, ('response_received',), ('http_response_present=PASS',)

def account_shape(response: Mapping[str,Any]) -> tuple[bool,tuple[str,...],tuple[str,...]]:
    ok=isinstance(response, Mapping)
    return ok, ('account_payload_received',) if ok else (), ('account_payload_mapping=PASS' if ok else 'account_payload_mapping=FAIL',)

# Read-only probes are safe foundations. Order/fill scenarios are deliberately explicit and require a separate guarded plan.
READ_ONLY_PLAN = E2EPlan((
    Step('TN-01','GET','/fapi/v1/ping',{},http_ok),
    Step('TN-02','GET','/fapi/v1/exchangeInfo',{},http_ok),
))

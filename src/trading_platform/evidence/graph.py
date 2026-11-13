from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable
from hashlib import sha256
import json

class EvidenceState(str, Enum):
    VALID='VALID'; SUSPENDED='SUSPENDED'; INVALIDATED='INVALIDATED'; REVALIDATED='REVALIDATED'; EXPIRED='EXPIRED'

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    evidence_type: str
    state: EvidenceState
    version: str
    created_at: str
    source_refs: tuple[str,...]
    dependencies: tuple[str,...]
    methodology_version: str
    scope: dict[str,str]
    validity_window: tuple[str|None,str|None]
    content_hash: str
    owner: str

@dataclass(frozen=True)
class EvidenceGraphNode:
    node_id: str
    node_type: str
    version: str
    upstream_dependencies: tuple[str,...]

class EvidenceDependencyGraph:
    def __init__(self, nodes: Iterable[EvidenceGraphNode]=()):
        self._nodes={n.node_id:n for n in nodes}
    def add(self,node:EvidenceGraphNode)->None:
        old=self._nodes.get(node.node_id)
        if old is not None and old != node: raise ValueError('IMMUTABLE_HISTORICAL_GRAPH_NODE')
        for dep in node.upstream_dependencies:
            if dep not in self._nodes: raise ValueError(f'MISSING_UPSTREAM:{dep}')
        self._nodes[node.node_id]=node
    def dependents(self,node_id:str)->tuple[str,...]:
        return tuple(sorted(n.node_id for n in self._nodes.values() if node_id in n.upstream_dependencies))
    def version_hash(self)->str:
        payload=[self._nodes[k].__dict__ for k in sorted(self._nodes)]
        return sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def snapshot(self)->dict[str,dict]:
        return {k:self._nodes[k].__dict__.copy() for k in sorted(self._nodes)}

@dataclass(frozen=True)
class InvalidationImpact:
    changed_component: str
    affected_artifacts: tuple[str,...]
    invalidated_evidence: tuple[str,...]
    invalidated_gates: tuple[str,...]
    affected_candidates: tuple[str,...]
    affected_promotions: tuple[str,...]
    required_revalidation: tuple[str,...]
    deployment_impact: str

def propagate_invalidation(graph: EvidenceDependencyGraph, changed_component: str, evidence_index: dict[str,Evidence], gate_dependencies: dict[str,tuple[str,...]], candidates: dict[str,tuple[str,...]], promotions: dict[str,tuple[str,...]]) -> InvalidationImpact:
    if not isinstance(changed_component, str) or not changed_component.strip():
        raise ValueError("INVALIDATION_COMPONENT_REQUIRED")
    seen=set(); stack=[changed_component]
    while stack:
        x=stack.pop()
        if x in seen: continue
        seen.add(x); stack.extend(graph.dependents(x))
    affected_evidence: set[str] = set()
    invalidated_gates: set[str] = set()
    affected_candidates: set[str] = set()
    affected_promotions: set[str] = set()
    impacted = set(seen)

    # Close the impact transitively across both graph nodes and the separate
    # evidence/gate/candidate/promotion registries. Evidence may depend on an
    # earlier evidence ID without appearing as a node in EvidenceDependencyGraph.
    changed = True
    while changed:
        changed = False
        for evidence_id, evidence in evidence_index.items():
            references = set(evidence.dependencies) | set(evidence.source_refs)
            if evidence_id in impacted or references & impacted:
                if evidence_id not in affected_evidence:
                    affected_evidence.add(evidence_id)
                    impacted.add(evidence_id)
                    changed = True
        for gate_id, dependencies in gate_dependencies.items():
            if gate_id in impacted or set(dependencies) & impacted:
                if gate_id not in invalidated_gates:
                    invalidated_gates.add(gate_id)
                    impacted.add(gate_id)
                    changed = True
        for candidate_id, dependencies in candidates.items():
            if candidate_id in impacted or set(dependencies) & impacted:
                if candidate_id not in affected_candidates:
                    affected_candidates.add(candidate_id)
                    impacted.add(candidate_id)
                    changed = True
        for promotion_id, dependencies in promotions.items():
            if promotion_id in impacted or set(dependencies) & impacted:
                if promotion_id not in affected_promotions:
                    affected_promotions.add(promotion_id)
                    impacted.add(promotion_id)
                    changed = True

    affected_evidence_result = tuple(sorted(affected_evidence))
    invalidated_gates_result = tuple(sorted(invalidated_gates))
    affected_candidates_result = tuple(sorted(affected_candidates))
    affected_promotions_result = tuple(sorted(affected_promotions))
    required_revalidation = tuple(sorted(impacted - {changed_component}))
    deployment_impact = "BLOCK_OR_REVALIDATE" if required_revalidation else "NO_REGISTERED_DEPENDENT_OBJECT"
    return InvalidationImpact(
        changed_component=changed_component,
        affected_artifacts=tuple(sorted(seen)),
        invalidated_evidence=affected_evidence_result,
        invalidated_gates=invalidated_gates_result,
        affected_candidates=affected_candidates_result,
        affected_promotions=affected_promotions_result,
        required_revalidation=required_revalidation,
        deployment_impact=deployment_impact,
    )

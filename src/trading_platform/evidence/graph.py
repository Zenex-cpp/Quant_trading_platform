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
    seen=set(); stack=[changed_component]
    while stack:
        x=stack.pop()
        if x in seen: continue
        seen.add(x); stack.extend(graph.dependents(x))
    affected_evidence=tuple(sorted(eid for eid,e in evidence_index.items() if eid in seen or bool(set(e.dependencies)&seen)))
    invalidated_gates=tuple(sorted(g for g,deps in gate_dependencies.items() if set(deps)&(seen|set(affected_evidence))))
    affected_candidates=tuple(sorted(c for c,deps in candidates.items() if set(deps)&(set(invalidated_gates)|set(affected_evidence))))
    affected_promotions=tuple(sorted(p for p,deps in promotions.items() if set(deps)&(set(affected_candidates)|set(invalidated_gates)|set(affected_evidence))))
    return InvalidationImpact(changed_component, tuple(sorted(seen)), affected_evidence, invalidated_gates, affected_candidates, affected_promotions, affected_promotions or affected_candidates and ('REVALIDATE',) or ('NONE',), 'BLOCK_OR_REVALIDATE' if affected_promotions else 'NO_CURRENT_DEPLOYMENT')

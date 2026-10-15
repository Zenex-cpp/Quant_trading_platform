"""Immutable-friendly evidence lineage graph for V0.3."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import json, hashlib

@dataclass(frozen=True)
class LineageNode:
    node_id: str
    node_type: str
    version: str
    upstream: tuple[str, ...]

class LineageGraph:
    def __init__(self, nodes: Iterable[LineageNode]=()):
        self._nodes = {n.node_id:n for n in nodes}
    def add(self, node: LineageNode) -> None:
        if node.node_id in self._nodes and self._nodes[node.node_id] != node:
            raise ValueError("IMMUTABLE_NODE_CHANGE")
        for dep in node.upstream:
            if dep not in self._nodes:
                raise ValueError(f"MISSING_UPSTREAM:{dep}")
        self._nodes[node.node_id]=node
    def version_hash(self) -> str:
        payload = [self._nodes[k].__dict__ for k in sorted(self._nodes)]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",",":")).encode()).hexdigest()
    def dependents(self, node_id: str) -> tuple[str,...]:
        return tuple(sorted(n.node_id for n in self._nodes.values() if node_id in n.upstream))
    def as_dict(self):
        return {k:self._nodes[k].__dict__ for k in sorted(self._nodes)}

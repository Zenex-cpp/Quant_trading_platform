from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class EdgeStatus(str, Enum):
    ACTIVE='ACTIVE'; WATCH='WATCH'; DEGRADED='DEGRADED'; RETIRED='RETIRED'

@dataclass(frozen=True)
class EdgeRecord:
    edge_id: str
    name: str
    hypothesis_id: str
    mechanism: str
    evidence_ids: tuple[str,...]
    best_regimes: tuple[str,...]
    worst_regimes: tuple[str,...]
    cost_sensitivity: str
    capacity: str
    decay: str
    confidence: str
    status: EdgeStatus

@dataclass(frozen=True)
class EdgeDecayObservation:
    phase: str
    evidence_id: str
    metric: float
    threshold: float
    timestamp: str

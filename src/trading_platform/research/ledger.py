from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json

class HypothesisStatus(str, Enum):
    OPEN='OPEN'; SUPPORTED='SUPPORTED'; DISPROVED='DISPROVED'; UNCERTAIN='UNCERTAIN'; OBSOLETE='OBSOLETE'

@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    statement: str
    motivation: str
    expected_mechanism: str
    falsification_criteria: str
    status: HypothesisStatus
    owner: str
    created_at: datetime

@dataclass(frozen=True)
class ResearchBranch:
    research_branch_id: str
    parent_branch_id: str | None
    hypothesis_id: str
    purpose: str
    branch_type: str
    status: str

@dataclass(frozen=True)
class ResearchDecision:
    decision_id: str
    research_branch_id: str
    action: str
    evidence: tuple[str, ...]
    rationale: str
    owner: str
    timestamp: datetime

@dataclass(frozen=True)
class DecisionBiasRecord:
    decision_id: str
    actor: str
    decision: str
    reason: str
    evidence_seen: tuple[str, ...]
    alternatives: tuple[str, ...]
    selection_effect: str
    timestamp: datetime

@dataclass(frozen=True)
class MergeRecord:
    merge_id: str
    parent_branches: tuple[str, ...]
    combined_lineage: tuple[str, ...]
    merged_hypotheses: tuple[str, ...]
    conflicts: tuple[str, ...]
    selection_rationale: str
    new_candidate_id: str

@dataclass(frozen=True)
class ResearchCost:
    research_compute_cost: float
    data_cost: float
    storage_cost: float
    training_cost: float
    inference_cost: float
    engineering_cost: float
    operational_cost: float
    @property
    def total_cost(self) -> float:
        return sum((self.research_compute_cost, self.data_cost, self.storage_cost, self.training_cost, self.inference_cost, self.engineering_cost, self.operational_cost))

def information_gain_priority(information_gain: float, cost: ResearchCost) -> float:
    if cost.total_cost <= 0:
        return float('inf')
    return information_gain / cost.total_cost

def stable_key(payload: object) -> str:
    return sha256(json.dumps(payload, default=str, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

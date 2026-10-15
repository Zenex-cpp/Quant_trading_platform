"""Research-family accounting and anti-cherry-picking registry primitives."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    research_family_id: str
    status: str
    selected: bool
    variant_hash: str
    dataset_version: str
    feature_version: str
    target_version: str
    model_version: str
    result_hash: str

@dataclass(frozen=True)
class FamilySummary:
    research_family_id: str
    total_experiments: int
    failed: int
    selected: int
    discarded: int


def summarize_family(records: list[ExperimentRecord], family_id: str) -> FamilySummary:
    r=[x for x in records if x.research_family_id==family_id]
    return FamilySummary(family_id, len(r), sum(x.status in {"FAILED","REJECTED"} for x in r), sum(x.selected for x in r), sum((not x.selected) for x in r))

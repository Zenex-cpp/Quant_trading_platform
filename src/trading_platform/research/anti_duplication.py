from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

@dataclass(frozen=True)
class ExperimentSignature:
    hypothesis: str
    dataset_version: str
    feature_version: str
    target_version: str
    strategy_version: str
    experiment_genealogy: tuple[str, ...]

@dataclass(frozen=True)
class SimilarityResult:
    similar: bool
    similarity_score: float
    matched_dimensions: tuple[str, ...]
    outcome: str

def _tokenize(value: str) -> set[str]:
    return {x for x in value.lower().replace('-', '_').split('_') if x}

def _jaccard(a: str, b: str) -> float:
    sa, sb = _tokenize(a), _tokenize(b)
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)

def compare_signature(candidate: ExperimentSignature, existing: Iterable[ExperimentSignature], threshold: float = 0.75) -> SimilarityResult:
    best = (0.0, ())
    for e in existing:
        dims = {
            'hypothesis': _jaccard(candidate.hypothesis, e.hypothesis),
            'dataset': float(candidate.dataset_version == e.dataset_version),
            'feature_set': float(candidate.feature_version == e.feature_version),
            'target': float(candidate.target_version == e.target_version),
            'strategy': float(candidate.strategy_version == e.strategy_version),
            'genealogy': float(bool(set(candidate.experiment_genealogy) & set(e.experiment_genealogy))),
        }
        matched = tuple(k for k,v in dims.items() if v >= threshold)
        score = sum(dims.values()) / len(dims)
        if score > best[0]: best = (score, matched)
    similar = best[0] >= threshold
    return SimilarityResult(similar, best[0], best[1], 'REUSE' if similar else 'JUSTIFY_NEW_EXPERIMENT')

def variant_hash(signature: ExperimentSignature) -> str:
    return sha256(json.dumps(signature.__dict__, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()

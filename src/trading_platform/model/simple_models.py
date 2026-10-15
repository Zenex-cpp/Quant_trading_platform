"""Small, auditable model wrappers. No production deployment path."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Sequence
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

@dataclass
class ModelFitResult:
    model: Any
    model_type: str
    feature_names: tuple[str, ...]
    training_rows: int

class LogisticBaseline:
    def __init__(self, *, C: float = 1.0, max_iter: int = 500):
        self.model = LogisticRegression(C=C, max_iter=max_iter, random_state=0)
    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int], feature_names: Sequence[str]) -> ModelFitResult:
        self.model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return ModelFitResult(self.model, "LOGISTIC", tuple(feature_names), len(y))
    def predict_proba(self, X):
        return self.model.predict_proba(np.asarray(X, dtype=float))

class DecisionTreeBaseline:
    def __init__(self, *, max_depth: int = 3, min_samples_leaf: int = 20):
        self.model = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=min_samples_leaf, random_state=0)
    def fit(self, X, y, feature_names):
        self.model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return ModelFitResult(self.model, "TREE", tuple(feature_names), len(y))
    def predict_proba(self, X):
        return self.model.predict_proba(np.asarray(X, dtype=float))

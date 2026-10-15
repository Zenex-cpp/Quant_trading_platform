"""V0.5 reproducible training/evaluation pipeline contracts.

No live execution. Final holdout access is structurally forbidden to tuning APIs.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Sequence, Any, Mapping

from trading_platform.data.holdout import TuningDataView
from trading_platform.security.credentials import assert_research_arguments
import numpy as np

from sklearn.base import clone


def stable_hash(obj: Any) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",",":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class SplitSpec:
    train_end: datetime
    validation_end: datetime
    oos_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    embargo: str
    purge: str
    version: str

    def validate(self) -> None:
        xs=(self.train_end,self.validation_end,self.oos_end,self.holdout_start,self.holdout_end)
        if any(x.tzinfo is None for x in xs): raise ValueError("SPLIT_TIMEZONE_REQUIRED")
        if not (self.train_end < self.validation_end < self.oos_end <= self.holdout_start < self.holdout_end):
            raise ValueError("INVALID_TEMPORAL_SPLIT")


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    research_family_id: str
    dataset_version: str
    feature_version: str
    target_version: str
    model_id: str
    model_version: str
    split_version: str
    seed: int
    code_version: str
    configuration_version: str

    def fingerprint(self) -> str:
        return stable_hash(asdict(self))


@dataclass(frozen=True)
class EvaluationResult:
    split: str
    n: int
    metric: str
    value: float
    methodology_version: str
    warning: str | None = None


def assert_no_holdout_in_tuning(split_name: str) -> None:
    if split_name.upper() == "FINAL_HOLDOUT":
        raise PermissionError("FINAL_HOLDOUT_TUNING_FORBIDDEN")


def chronological_split(times: Sequence[datetime], spec: SplitSpec) -> dict[str, np.ndarray]:
    spec.validate()
    t=np.asarray(times, dtype=object)
    return {
        "TRAIN": np.where(t <= spec.train_end)[0],
        "VALIDATION": np.where((t > spec.train_end) & (t <= spec.validation_end))[0],
        "OOS": np.where((t > spec.validation_end) & (t <= spec.oos_end))[0],
        "FINAL_HOLDOUT": np.where((t >= spec.holdout_start) & (t <= spec.holdout_end))[0],
    }


class TuningSession:
    """Tuning workflow surface. Final holdout is deliberately absent."""

    __slots__ = ("__view", "__split_version")

    def __init__(self, *, times: Sequence[datetime], spec: SplitSpec, rows: Sequence[Any]) -> None:
        assert_research_arguments(times, spec, rows)
        if len(times) != len(rows):
            raise ValueError("TUNING_INPUT_LENGTH_MISMATCH")
        indices = chronological_split(times, spec)
        self.__view = TuningDataView(
            train=[rows[int(i)] for i in indices["TRAIN"]],
            validation=[rows[int(i)] for i in indices["VALIDATION"]],
            oos=[rows[int(i)] for i in indices["OOS"]],
        )
        self.__split_version = spec.version

    @property
    def data(self) -> TuningDataView:
        return self.__view

    @property
    def split_version(self) -> str:
        return self.__split_version

    def evaluate_split(self, split_name: str, evaluator, *args, **kwargs):
        assert_research_arguments(args, kwargs)
        assert_no_holdout_in_tuning(split_name)
        name = split_name.upper()
        data = {
            "TRAIN": self.__view.train,
            "VALIDATION": self.__view.validation,
            "OOS": self.__view.oos,
        }.get(name)
        if data is None:
            raise ValueError("TUNING_SPLIT_NOT_AVAILABLE")
        return evaluator(data, *args, **kwargs)


def fit_on_train_only(estimator, X, y, train_idx: Sequence[int]):
    assert_research_arguments(estimator, X, y, train_idx)
    if len(train_idx)==0: raise ValueError("EMPTY_TRAIN_SPLIT")
    est=clone(estimator)
    est.fit(np.asarray(X)[list(train_idx)], np.asarray(y)[list(train_idx)])
    return est

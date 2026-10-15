"""Leakage-aware chronological validation splits."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence, Any

@dataclass(frozen=True)
class Split:
    train: tuple[int, ...]
    validation: tuple[int, ...]
    oos: tuple[int, ...]
    final_holdout: tuple[int, ...]
    purged: tuple[int, ...]
    embargoed: tuple[int, ...]

@dataclass(frozen=True)
class LabelInterval:
    start: datetime
    end: datetime


def chronological_split(
    n: int, *, train_frac: float=.60, validation_frac: float=.15, oos_frac: float=.15,
    label_end: Sequence[datetime] | None=None, embargo: timedelta=timedelta(0), holdout_frac: float=.10
) -> Split:
    if n < 4 or min(train_frac, validation_frac, oos_frac, holdout_frac) <= 0:
        raise ValueError("INVALID_SPLIT_CONFIGURATION")
    total = train_frac + validation_frac + oos_frac + holdout_frac
    if abs(total - 1.0) > 1e-9: raise ValueError("SPLIT_FRACTIONS_MUST_SUM_TO_ONE")
    a = int(n * train_frac); b = a + int(n * validation_frac); c = b + int(n * oos_frac)
    train = list(range(0,a)); val = list(range(a,b)); oos = list(range(b,c)); hold = list(range(c,n))
    purged: set[int] = set(); embargoed: set[int] = set()
    if label_end is not None:
        if len(label_end) != n: raise ValueError("LABEL_END_LENGTH_MISMATCH")
        # Purge train rows whose label horizon crosses validation start.
        v_start = label_end[a] if a < n else label_end[-1]
        for i in list(train):
            if label_end[i] >= v_start: purged.add(i)
        train = [i for i in train if i not in purged]
        if embargo > timedelta(0) and val:
            embargo_end = label_end[b-1] + embargo if b > 0 else None
            if embargo_end is not None:
                for i in oos:
                    # Caller supplies chronological label end; comparing end timestamp
                    # creates a conservative embargo after validation.
                    if label_end[i] <= embargo_end: embargoed.add(i)
                oos = [i for i in oos if i not in embargoed]
    return Split(tuple(train), tuple(val), tuple(oos), tuple(hold), tuple(sorted(purged)), tuple(sorted(embargoed)))

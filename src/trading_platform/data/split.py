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
    label_end: Sequence[datetime] | None=None, event_time: Sequence[datetime] | None=None,
    embargo: timedelta=timedelta(0), holdout_frac: float=.10
) -> Split:
    """Create chronological sets and purge labels across every later boundary.

    When target intervals are supplied, their event timestamps are required so a
    sample's label end can be compared with the actual start time of the next set.
    """
    if n < 4 or min(train_frac, validation_frac, oos_frac, holdout_frac) <= 0:
        raise ValueError("INVALID_SPLIT_CONFIGURATION")
    if embargo < timedelta(0):
        raise ValueError("EMBARGO_MUST_NOT_BE_NEGATIVE")
    total = train_frac + validation_frac + oos_frac + holdout_frac
    if abs(total - 1.0) > 1e-9: raise ValueError("SPLIT_FRACTIONS_MUST_SUM_TO_ONE")
    a = int(n * train_frac); b = a + int(n * validation_frac); c = b + int(n * oos_frac)
    if not (0 < a < b < c < n):
        raise ValueError("SPLIT_CONFIGURATION_PRODUCES_EMPTY_SPLIT")
    train = list(range(0,a)); val = list(range(a,b)); oos = list(range(b,c)); hold = list(range(c,n))
    purged: set[int] = set(); embargoed: set[int] = set()
    if label_end is not None:
        if len(label_end) != n: raise ValueError("LABEL_END_LENGTH_MISMATCH")
        if event_time is None:
            raise ValueError("EVENT_TIME_REQUIRED_FOR_PURGED_SPLIT")
        if len(event_time) != n: raise ValueError("EVENT_TIME_LENGTH_MISMATCH")
        try:
            if any(event_time[i] < event_time[i - 1] for i in range(1, n)):
                raise ValueError("EVENT_TIME_NOT_CHRONOLOGICAL")
            if any(label_end[i] < event_time[i] for i in range(n)):
                raise ValueError("LABEL_END_BEFORE_EVENT_TIME")
        except TypeError as exc:
            raise ValueError("SPLIT_TIMES_NOT_COMPARABLE") from exc

        segments = [train, val, oos, hold]
        boundaries = (a, b, c)
        # Purge every sample whose target interval reaches the next split. Purging
        # only train rows allows validation/OOS labels to consume the holdout.
        for source, boundary in zip(segments[:3], boundaries):
            boundary_time = event_time[boundary]
            kept = []
            for index in source:
                if label_end[index] >= boundary_time:
                    purged.add(index)
                else:
                    kept.append(index)
            source[:] = kept

        if embargo > timedelta(0):
            for source, destination in zip(segments[:-1], segments[1:]):
                if not source or not destination:
                    continue
                embargo_end = max(label_end[index] for index in source) + embargo
                kept = []
                for index in destination:
                    if event_time[index] <= embargo_end:
                        embargoed.add(index)
                    else:
                        kept.append(index)
                destination[:] = kept
    elif embargo != timedelta(0):
        raise ValueError("LABEL_END_REQUIRED_FOR_EMBARGO")
    if not train or not val or not oos or not hold:
        raise ValueError("PURGE_OR_EMBARGO_EMPTIED_SPLIT")
    return Split(tuple(train), tuple(val), tuple(oos), tuple(hold), tuple(sorted(purged)), tuple(sorted(embargoed)))

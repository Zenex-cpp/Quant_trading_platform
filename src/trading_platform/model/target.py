"""Versioned target/label engine for point-in-time research."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

@dataclass(frozen=True)
class TargetSpec:
    target_id: str
    version: str
    horizon: timedelta
    entry_definition: str
    exit_definition: str
    cost_assumption: str
    labeling_method: str
    overlap_policy: str
    class_balance: str
    missing_label_policy: str

@dataclass(frozen=True)
class Label:
    target_id: str
    target_version: str
    index: int
    value: float | int | None
    label_start: object
    label_end: object
    available_at: object


def future_return_labels(prices: Sequence[float], timestamps: Sequence[object], spec: TargetSpec,
                         cost_bps: float = 0.0) -> tuple[Label, ...]:
    if len(prices) != len(timestamps):
        raise ValueError("TARGET_INPUT_LENGTH_MISMATCH")
    if spec.horizon <= timedelta(0):
        raise ValueError("TARGET_HORIZON_MUST_BE_POSITIVE")
    # The target becomes available only at label_end. It is never available at entry time.
    minutes = max(1, int(spec.horizon.total_seconds() // 60))
    out: list[Label] = []
    for i in range(len(prices)):
        j = i + minutes
        if j >= len(prices):
            if spec.missing_label_policy == "DROP":
                continue
            out.append(Label(spec.target_id, spec.version, i, None, timestamps[i], timestamps[-1], timestamps[-1]))
            continue
        p0, p1 = float(prices[i]), float(prices[j])
        net = (p1 / p0) - 1.0 - (2.0 * cost_bps / 10000.0)
        out.append(Label(spec.target_id, spec.version, i, net, timestamps[i], timestamps[j], timestamps[j]))
    return tuple(out)

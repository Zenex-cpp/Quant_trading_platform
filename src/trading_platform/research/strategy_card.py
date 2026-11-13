"""Immutable machine-readable strategy card template for V5.0 research."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json


@dataclass(frozen=True)
class StrategyCard:
    strategy_id: str
    strategy_version: str
    hypothesis: str
    intended_use: str
    validity_scope: str
    instruments: tuple[str, ...]
    timeframes: tuple[str, ...]
    regimes: tuple[str, ...]
    prohibited_regimes: tuple[str, ...]
    entry_logic: str
    exit_logic: str
    signal_dependencies: tuple[str, ...]
    portfolio_constraints: str
    risk_controls: str
    data_requirements: tuple[str, ...]
    execution_assumptions: str
    cost_assumptions: str
    capacity_limits: str
    turnover_limits: str
    monitoring_metrics: tuple[str, ...]
    known_limitations: str
    failure_modes: str
    dependencies: tuple[str, ...]
    owner: str
    approval_scope: str

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            label = field.name.upper()
            if isinstance(value, str):
                if not value.strip():
                    raise ValueError(f"STRATEGY_CARD_{label}_REQUIRED")
                continue
            if not isinstance(value, tuple):
                raise ValueError(f"STRATEGY_CARD_{label}_MUST_BE_TUPLE")
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"STRATEGY_CARD_{label}_ITEM_INVALID")
            if len(set(value)) != len(value):
                raise ValueError(f"STRATEGY_CARD_{label}_DUPLICATE_ITEM")

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def fingerprint(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

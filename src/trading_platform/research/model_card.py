"""Machine-readable model card template."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelCard:
    model_id: str
    model_version: str
    intended_use: str
    validity_scope: str
    training_data: str
    features: str
    target: str
    regimes: str
    prohibited_regimes: str
    limitations: str
    failure_modes: str
    dependencies: str
    capital_range: str
    venues: str
    timeframes: str
    execution_assumptions: str
    approval_scope: str

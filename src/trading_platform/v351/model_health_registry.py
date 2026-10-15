from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelHealthMethodSpec:
    method: str
    version: str
    definition: str
    minimum_health: str
    maximum_health: str
    action: str
    monitoring: str
    source_binding: str


PRODUCTION_MODEL_HEALTH_METHODS: tuple[ModelHealthMethodSpec, ...] = (
    ModelHealthMethodSpec(
        method="CONSERVATIVE_LINEAR",
        version="1",
        definition="risk_factor=max(floor, min(1, model_health/max_model_health))",
        minimum_health="0",
        maximum_health="1",
        action="WORSE_MODEL_HEALTH_REDUCES_OR_PRESERVES_RISK",
        monitoring="MONOTONICITY_ABLATION_AND_SOURCE_FRESHNESS_REQUIRED",
        source_binding="assessment_id_required;health_evidence_must_be_fresh_and_verified",
    ),
)


def get_production_model_health_method(method: str, version: str) -> ModelHealthMethodSpec:
    for spec in PRODUCTION_MODEL_HEALTH_METHODS:
        if spec.method == method and spec.version == version:
            return spec
    raise ValueError("MODEL_HEALTH_METHOD_NOT_REGISTERED")

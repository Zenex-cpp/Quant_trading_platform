from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UncertaintyMethodSpec:
    method: str
    version: str
    definition: str
    minimum_uncertainty: str
    maximum_uncertainty: str
    action: str
    monitoring: str


PRODUCTION_UNCERTAINTY_METHODS: tuple[UncertaintyMethodSpec, ...] = (
    UncertaintyMethodSpec(
        method="CONSERVATIVE_LINEAR",
        version="1",
        definition="risk_factor=max(floor, 1-min(1, uncertainty/max_uncertainty))",
        minimum_uncertainty="0",
        maximum_uncertainty="1",
        action="HIGHER_UNCERTAINTY_REDUCES_OR_PRESERVES_RISK",
        monitoring="MONOTONICITY_ABLATION_REQUIRED",
    ),
)


def get_production_uncertainty_method(method: str, version: str) -> UncertaintyMethodSpec:
    for spec in PRODUCTION_UNCERTAINTY_METHODS:
        if spec.method == method and spec.version == version:
            return spec
    raise ValueError("UNCERTAINTY_METHOD_NOT_REGISTERED")

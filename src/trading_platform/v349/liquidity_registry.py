from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiquidityMethodSpec:
    method: str
    version: str
    definition: str
    minimum_stress: str
    maximum_stress: str
    action: str
    monitoring: str


PRODUCTION_LIQUIDITY_METHODS: tuple[LiquidityMethodSpec, ...] = (
    LiquidityMethodSpec(
        method="CONSERVATIVE_LINEAR",
        version="1",
        definition="risk_factor=max(floor, 1-min(1, liquidity_stress/max_stress))",
        minimum_stress="0",
        maximum_stress="1",
        action="HIGHER_LIQUIDITY_STRESS_REDUCES_OR_PRESERVES_RISK",
        monitoring="MONOTONICITY_ABLATION_REQUIRED",
    ),
)


def get_production_liquidity_method(method: str, version: str) -> LiquidityMethodSpec:
    for spec in PRODUCTION_LIQUIDITY_METHODS:
        if spec.method == method and spec.version == version:
            return spec
    raise ValueError("LIQUIDITY_METHOD_NOT_REGISTERED")

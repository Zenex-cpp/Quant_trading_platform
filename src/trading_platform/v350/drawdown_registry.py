from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrawdownMethodSpec:
    method: str
    version: str
    definition: str
    minimum_drawdown: str
    maximum_drawdown: str
    action: str
    monitoring: str


PRODUCTION_DRAWDOWN_METHODS: tuple[DrawdownMethodSpec, ...] = (
    DrawdownMethodSpec(
        method="CONSERVATIVE_LINEAR",
        version="1",
        definition="risk_factor=max(floor, 1-min(1, drawdown/max_drawdown))",
        minimum_drawdown="0",
        maximum_drawdown="1",
        action="HIGHER_DRAWDOWN_REDUCES_OR_PRESERVES_RISK",
        monitoring="MONOTONICITY_ABLATION_REQUIRED",
    ),
)


def get_production_drawdown_method(method: str, version: str) -> DrawdownMethodSpec:
    for spec in PRODUCTION_DRAWDOWN_METHODS:
        if spec.method == method and spec.version == version:
            return spec
    raise ValueError("DRAWDOWN_METHOD_NOT_REGISTERED")

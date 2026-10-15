"""V3.50 — M23 drawdown/risk budget monotonicity authority."""

from .drawdown_registry import PRODUCTION_DRAWDOWN_METHODS, DrawdownMethodSpec, get_production_drawdown_method
from .drawdown_risk_authority import (
    DrawdownRiskBinding,
    DrawdownRiskError,
    assert_drawdown_monotone,
    bind_drawdown_to_risk,
    conservative_drawdown_factor_decimal,
    validate_drawdown_factor,
)

__all__ = [
    "PRODUCTION_DRAWDOWN_METHODS",
    "DrawdownMethodSpec",
    "get_production_drawdown_method",
    "DrawdownRiskBinding",
    "DrawdownRiskError",
    "assert_drawdown_monotone",
    "bind_drawdown_to_risk",
    "conservative_drawdown_factor_decimal",
    "validate_drawdown_factor",
]

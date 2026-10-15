from decimal import Decimal

from trading_platform.v348.uncertainty_risk_authority import validate_uncertainty_factor, conservative_risk_factor_decimal
from trading_platform.v349.liquidity_risk_authority import validate_liquidity_factor, conservative_liquidity_factor_decimal
from trading_platform.v350.drawdown_risk_authority import validate_drawdown_factor, conservative_drawdown_factor_decimal
from trading_platform.v351.model_health_risk_authority import validate_model_health_factor, conservative_model_health_factor_decimal
from trading_platform.v356.risk_state_monotonicity import validate_state_risk_factor

def adjusted_risk(base: Decimal, *, signal_quality: Decimal = Decimal("1"), uncertainty_factor: Decimal = Decimal("1"), uncertainty: Decimal | None = None, max_uncertainty: Decimal = Decimal("1"), uncertainty_floor: Decimal = Decimal("0"), regime_factor: Decimal = Decimal("1"), volatility_factor: Decimal = Decimal("1"), liquidity_factor: Decimal = Decimal("1"), liquidity_stress: Decimal | None = None, max_liquidity_stress: Decimal = Decimal("1"), liquidity_floor: Decimal = Decimal("0"), drawdown_factor: Decimal = Decimal("1"), drawdown: Decimal | None = None, max_drawdown: Decimal = Decimal("1"), drawdown_floor: Decimal = Decimal("0"), model_health_factor: Decimal = Decimal("1"), model_health: Decimal | None = None, max_model_health: Decimal = Decimal("1"), model_health_floor: Decimal = Decimal("0"), state_risk_factor: Decimal = Decimal("1")) -> Decimal:
    if uncertainty is not None:
        derived_factor = conservative_risk_factor_decimal(uncertainty, max_uncertainty=max_uncertainty, floor=uncertainty_floor)
        if uncertainty_factor != Decimal("1") and uncertainty_factor != derived_factor:
            raise ValueError("UNCERTAINTY_FACTOR_CONFLICT")
        uncertainty_factor = derived_factor
    else:
        uncertainty_factor = validate_uncertainty_factor(uncertainty_factor)
    if liquidity_stress is not None:
        derived_liquidity_factor = conservative_liquidity_factor_decimal(liquidity_stress, max_stress=max_liquidity_stress, floor=liquidity_floor)
        if liquidity_factor != Decimal("1") and liquidity_factor != derived_liquidity_factor:
            raise ValueError("LIQUIDITY_FACTOR_CONFLICT")
        liquidity_factor = derived_liquidity_factor
    else:
        liquidity_factor = validate_liquidity_factor(liquidity_factor)
    if drawdown is not None:
        derived_drawdown_factor = conservative_drawdown_factor_decimal(drawdown, max_drawdown=max_drawdown, floor=drawdown_floor)
        if drawdown_factor != Decimal("1") and drawdown_factor != derived_drawdown_factor:
            raise ValueError("DRAWDOWN_FACTOR_CONFLICT")
        drawdown_factor = derived_drawdown_factor
    else:
        drawdown_factor = validate_drawdown_factor(drawdown_factor)
    if model_health is not None:
        derived_model_health_factor = conservative_model_health_factor_decimal(model_health, max_model_health=max_model_health, floor=model_health_floor)
        if model_health_factor != Decimal("1") and model_health_factor != derived_model_health_factor:
            raise ValueError("MODEL_HEALTH_FACTOR_CONFLICT")
        model_health_factor = derived_model_health_factor
    else:
        model_health_factor = validate_model_health_factor(model_health_factor)
    state_risk_factor = validate_state_risk_factor(state_risk_factor)
    factors=(signal_quality, uncertainty_factor, regime_factor, volatility_factor, liquidity_factor, drawdown_factor, model_health_factor, state_risk_factor)
    if base < 0 or any(f < 0 for f in factors):
        raise ValueError("NEGATIVE_RISK_INPUT")
    result=base
    for factor in factors:
        result *= factor
    return result

def assert_risk_ceiling(effective_risk: Decimal, absolute_ceiling: Decimal, exposure: Decimal, absolute_exposure_ceiling: Decimal) -> None:
    if effective_risk > absolute_ceiling:
        raise ValueError("ABSOLUTE_RISK_CEILING_BREACH")
    if exposure > absolute_exposure_ceiling:
        raise ValueError("ABSOLUTE_EXPOSURE_CEILING_BREACH")

def assert_monotone_nonincrease(worse_value: Decimal, better_value: Decimal, *, tolerance: Decimal = Decimal("0")) -> None:
    if worse_value > better_value + tolerance:
        raise AssertionError("RISK_MONOTONICITY_BREACH")

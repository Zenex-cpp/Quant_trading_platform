from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class CapacityInputs:
    adv_notional: Decimal
    order_notional: Decimal
    participation_rate: Decimal
    spread_bps: Decimal
    price_impact_bps: Decimal

@dataclass(frozen=True)
class CapacityResult:
    capacity_notional: Decimal
    utilization: Decimal
    binding_constraint: str

def estimate_capacity(adv_notional: Decimal, max_participation: Decimal, impact_budget_bps: Decimal, impact_per_participation_bps: Decimal) -> CapacityResult:
    if adv_notional<=0 or max_participation<=0 or impact_budget_bps<0 or impact_per_participation_bps<=0: raise ValueError("INVALID_CAPACITY_INPUT")
    by_participation=adv_notional*max_participation
    by_impact=adv_notional*(impact_budget_bps/impact_per_participation_bps)
    cap=min(by_participation,by_impact)
    binding='PARTICIPATION' if by_participation<=by_impact else 'IMPACT'
    return CapacityResult(cap,Decimal('1') if cap==0 else Decimal('0'),binding)

def utilization(order_notional: Decimal, capacity_notional: Decimal)->Decimal:
    if order_notional<0 or capacity_notional<=0: raise ValueError("INVALID_CAPACITY_UTILIZATION")
    return order_notional/capacity_notional

def assert_capacity(order_notional: Decimal, capacity_notional: Decimal)->None:
    if order_notional<0: raise ValueError("NEGATIVE_ORDER_NOTIONAL")
    if order_notional>capacity_notional: raise ValueError("CAPACITY_BREACH")


def assert_capacity_monotone(*, lower_liquidity_capacity: Decimal, higher_liquidity_stress_capacity: Decimal) -> None:
    if lower_liquidity_capacity < 0 or higher_liquidity_stress_capacity < 0:
        raise ValueError("INVALID_CAPACITY_MONOTONICITY_INPUT")
    if higher_liquidity_stress_capacity > lower_liquidity_capacity:
        raise ValueError("CAPACITY_MONOTONICITY_BREACH_LIQUIDITY")

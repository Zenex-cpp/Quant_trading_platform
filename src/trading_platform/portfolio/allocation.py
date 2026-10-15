from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

class AllocationMethod(str, Enum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    INVERSE_VOL = "INVERSE_VOL"
    RISK_PARITY = "RISK_PARITY"
    VOL_TARGET = "VOL_TARGET"
    MEAN_VARIANCE = "MEAN_VARIANCE"
    CVAR = "CVAR"
    ROBUST = "ROBUST"
    REGIME_CONDITIONED = "REGIME_CONDITIONED"

@dataclass(frozen=True)
class PortfolioConstraints:
    max_gross_exposure: Decimal
    max_net_exposure: Decimal
    max_leverage: Decimal
    max_concentration: Decimal
    max_liquidity_utilization: Decimal
    turnover_budget: Decimal
    minimum_trade_threshold: Decimal

    def validate(self) -> None:
        vals=(self.max_gross_exposure,self.max_net_exposure,self.max_leverage,self.max_concentration,self.max_liquidity_utilization,self.turnover_budget,self.minimum_trade_threshold)
        if any(v<0 for v in vals): raise ValueError("NEGATIVE_PORTFOLIO_CONSTRAINT")
        if self.max_concentration>Decimal('1'): raise ValueError("INVALID_CONCENTRATION_LIMIT")
        if self.max_liquidity_utilization>Decimal('1'): raise ValueError("INVALID_LIQUIDITY_UTILIZATION_LIMIT")

@dataclass(frozen=True)
class AllocationInput:
    expected_return: Decimal
    risk: Decimal
    volatility: Decimal
    liquidity: Decimal
    capacity: Decimal
    uncertainty: Decimal
    model_health_factor: Decimal
    current_weight: Decimal = Decimal('0')

@dataclass(frozen=True)
class AllocationDecision:
    allocation_id: str
    portfolio_version: str
    timestamp: str
    valid_from: str
    expires_at: str
    methodology_version: str
    method: AllocationMethod
    weights: Mapping[str, Decimal]
    turnover: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    liquidity_utilization: Decimal
    risk_contribution: Mapping[str, Decimal]
    constraints_version: str
    inputs_hash: str
    risk_state: str
    evidence_refs: tuple[str,...] = ()

def _sanitize(x: Decimal) -> Decimal:
    if x<0: raise ValueError("NEGATIVE_ALLOCATION_INPUT")
    return x

def allocate_equal_weight(keys: Sequence[str]) -> dict[str, Decimal]:
    if not keys: return {}
    keys=list(keys)
    w=Decimal('1')/Decimal(len(keys))
    result={k:w for k in keys[:-1]}
    result[keys[-1]]=Decimal('1')-sum(result.values(),Decimal('0'))
    return result

def allocate_inverse_vol(inputs: Mapping[str, AllocationInput]) -> dict[str, Decimal]:
    scores={k:(Decimal('1')/v.volatility if v.volatility>0 else Decimal('0')) for k,v in inputs.items()}
    total=sum(scores.values(),Decimal('0'))
    if total<=0: return allocate_equal_weight(list(inputs))
    return {k:s/total for k,s in scores.items()}

def apply_hard_constraints(weights: Mapping[str, Decimal], constraints: PortfolioConstraints, gross: Decimal, net: Decimal, liquidity: Decimal) -> dict[str,Decimal]:
    constraints.validate()
    if gross>constraints.max_gross_exposure: raise ValueError("GROSS_EXPOSURE_CONSTRAINT")
    if abs(net)>constraints.max_net_exposure: raise ValueError("NET_EXPOSURE_CONSTRAINT")
    if gross>constraints.max_leverage: raise ValueError("LEVERAGE_CONSTRAINT")
    if liquidity>constraints.max_liquidity_utilization: raise ValueError("LIQUIDITY_CONSTRAINT")
    if any(abs(w)>constraints.max_concentration for w in weights.values()): raise ValueError("CONCENTRATION_CONSTRAINT")
    return dict(weights)

def turnover(current: Mapping[str,Decimal], target: Mapping[str,Decimal]) -> Decimal:
    keys=set(current)|set(target)
    return sum((abs(target.get(k,Decimal('0'))-current.get(k,Decimal('0'))) for k in keys),Decimal('0'))

def enforce_turnover(current: Mapping[str,Decimal], target: Mapping[str,Decimal], budget: Decimal, minimum_trade_threshold: Decimal) -> dict[str,Decimal]:
    raw={k:w for k,w in target.items() if abs(w-current.get(k,Decimal('0'))) >= minimum_trade_threshold}
    t=turnover(current,raw)
    if t>budget: raise ValueError("TURNOVER_BUDGET_EXCEEDED")
    return raw

def enforce_uncertainty_monotonicity(base_weights: Mapping[str,Decimal], inputs: Mapping[str,AllocationInput], worse: Mapping[str,AllocationInput]) -> None:
    for k,w in base_weights.items():
        if worse[k].uncertainty>inputs[k].uncertainty and worse[k].model_health_factor<inputs[k].model_health_factor and worse[k].liquidity>inputs[k].liquidity:
            if w < 0: raise ValueError("INVALID_BASE_WEIGHT")

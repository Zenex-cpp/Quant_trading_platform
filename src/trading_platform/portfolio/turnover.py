from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

@dataclass(frozen=True)
class TurnoverPolicy:
    budget: Decimal
    minimum_trade_threshold: Decimal
    transaction_cost_threshold: Decimal
    rebalance_frequency: str

def net_turnover(current: Mapping[str,Decimal], target: Mapping[str,Decimal])->Decimal:
    return sum((abs(target.get(k,Decimal('0'))-current.get(k,Decimal('0'))) for k in set(current)|set(target)),Decimal('0'))

def should_rebalance(current: Mapping[str,Decimal], target: Mapping[str,Decimal], estimated_cost_bps: Decimal, policy: TurnoverPolicy)->bool:
    t=net_turnover(current,target)
    if t>policy.budget: return False
    if t<policy.minimum_trade_threshold: return False
    if estimated_cost_bps>policy.transaction_cost_threshold: return False
    return True

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class FillPnLAttribution:
    fill_id: str
    order_id: str
    symbol: str
    trade_fee: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    execution_impact: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    market_impact: Decimal = Decimal("0")
    carrying_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    @property
    def total_cost(self) -> Decimal:
        return self.trade_fee + self.funding + self.execution_impact + self.slippage + self.market_impact + self.carrying_cost

@dataclass(frozen=True)
class CostBucket:
    trade_fee: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    execution_impact: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    market_impact: Decimal = Decimal("0")
    carrying_cost: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.trade_fee + self.funding + self.execution_impact + self.slippage + self.market_impact + self.carrying_cost

class PnLLedger:
    def __init__(self) -> None:
        self._fills: dict[str, FillPnLAttribution] = {}

    def apply(self, attribution: FillPnLAttribution) -> FillPnLAttribution:
        if not attribution.fill_id or not attribution.order_id or not attribution.symbol:
            raise ValueError("INVALID_PNL_ATTRIBUTION_ID")
        if attribution.fill_id in self._fills:
            prior = self._fills[attribution.fill_id]
            if prior != attribution:
                raise ValueError("FILL_PNL_ID_REUSE_WITH_DIFFERENT_CONTENT")
            return prior
        values = [attribution.trade_fee, attribution.funding, attribution.execution_impact, attribution.slippage,
                  attribution.market_impact, attribution.carrying_cost, attribution.realized_pnl]
        if any(not v.is_finite() for v in values):
            raise ValueError("NON_FINITE_PNL")
        self._fills[attribution.fill_id] = attribution
        return attribution

    def aggregate(self) -> tuple[Decimal, CostBucket]:
        realized = sum((v.realized_pnl for v in self._fills.values()), Decimal("0"))
        costs = CostBucket(
            trade_fee=sum((v.trade_fee for v in self._fills.values()), Decimal("0")),
            funding=sum((v.funding for v in self._fills.values()), Decimal("0")),
            execution_impact=sum((v.execution_impact for v in self._fills.values()), Decimal("0")),
            slippage=sum((v.slippage for v in self._fills.values()), Decimal("0")),
            market_impact=sum((v.market_impact for v in self._fills.values()), Decimal("0")),
            carrying_cost=sum((v.carrying_cost for v in self._fills.values()), Decimal("0")),
        )
        return realized, costs

    def entries(self) -> tuple[FillPnLAttribution, ...]:
        return tuple(self._fills.values())

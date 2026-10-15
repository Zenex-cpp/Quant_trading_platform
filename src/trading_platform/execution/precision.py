from dataclasses import dataclass
from decimal import Decimal
from decimal import ROUND_DOWN

@dataclass(frozen=True)
class InstrumentRules:
    tick_size:Decimal
    step_size:Decimal
    min_qty:Decimal
    min_notional:Decimal|None=None

    def normalize_price(self, price:Decimal)->Decimal:
        if self.tick_size<=0: raise ValueError('INVALID_TICK_SIZE')
        return (price/self.tick_size).to_integral_value(rounding=ROUND_DOWN)*self.tick_size
    def normalize_qty(self, qty:Decimal)->Decimal:
        if self.step_size<=0: raise ValueError('INVALID_STEP_SIZE')
        q=(qty/self.step_size).to_integral_value(rounding=ROUND_DOWN)*self.step_size
        if q<self.min_qty: raise ValueError('MIN_QTY_VIOLATION')
        return q
    def validate_notional(self, qty:Decimal, price:Decimal)->None:
        if self.min_notional is not None and qty*price < self.min_notional: raise ValueError('MIN_NOTIONAL_VIOLATION')

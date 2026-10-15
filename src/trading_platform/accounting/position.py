from dataclasses import dataclass
from decimal import Decimal
from trading_platform.execution.models import Fill, Side, PositionState

@dataclass
class Position:
    symbol: str
    quantity: Decimal=Decimal("0")
    average_entry_price: Decimal=Decimal("0")
    state: PositionState=PositionState.FLAT

class PositionLedger:
    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}

    def apply_fill(self, symbol: str, fill: Fill, side: Side) -> Position:
        p=self.positions.setdefault(symbol, Position(symbol))
        signed=fill.quantity if side==Side.BUY else -fill.quantity
        new_qty=p.quantity + signed
        if new_qty == 0:
            p.quantity=Decimal("0"); p.state=PositionState.CLOSED; p.average_entry_price=Decimal("0")
            return p
        if p.quantity == 0:
            p.quantity=new_qty; p.average_entry_price=fill.price; p.state=PositionState.OPEN; return p
        if (p.quantity > 0 and signed > 0) or (p.quantity < 0 and signed < 0):
            total=abs(p.quantity)+abs(signed)
            p.average_entry_price=((abs(p.quantity)*p.average_entry_price)+(abs(signed)*fill.price))/total
        p.quantity=new_qty
        p.state=PositionState.OPEN if new_qty != 0 else PositionState.CLOSED
        return p

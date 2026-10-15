from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from .orderbook import OrderBook

@dataclass(frozen=True)
class MicrostructureSnapshot:
    best_bid: Decimal
    best_ask: Decimal
    mid: Decimal
    spread: Decimal
    spread_bps: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    imbalance: Decimal

def compute_microstructure(book: OrderBook, levels: int = 5) -> MicrostructureSnapshot:
    if levels <= 0: raise ValueError("INVALID_DEPTH_LEVELS")
    bid, ask = book.best_bid(), book.best_ask()
    if bid is None or ask is None:
        raise ValueError("ORDERBOOK_NOT_SYNCHRONIZED")
    mid=(bid+ask)/Decimal('2')
    spread=ask-bid
    bsum=sum((q for _,q in sorted(book.bids.items(), reverse=True)[:levels]), Decimal('0'))
    asum=sum((q for _,q in sorted(book.asks.items())[:levels]), Decimal('0'))
    total=bsum+asum
    imbalance=Decimal('0') if total==0 else (bsum-asum)/total
    return MicrostructureSnapshot(bid,ask,mid,spread,(spread/mid)*Decimal('10000'),bsum,asum,imbalance)

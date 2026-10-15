from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable

class OrderBookStatus(str, Enum):
    EMPTY = "EMPTY"
    SYNCHRONIZED = "SYNCHRONIZED"
    GAP_DETECTED = "GAP_DETECTED"
    STALE = "STALE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

@dataclass(frozen=True)
class OrderBookSnapshot:
    last_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

@dataclass(frozen=True)
class OrderBookDiff:
    first_update_id: int
    final_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

@dataclass
class OrderBook:
    symbol: str
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    last_update_id: int | None = None
    status: OrderBookStatus = OrderBookStatus.EMPTY
    _buffer: list[OrderBookDiff] = field(default_factory=list)

    def load_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        self._validate_levels(snapshot.bids, is_bid=True)
        self._validate_levels(snapshot.asks, is_bid=False)
        self._validate_crossed(snapshot.bids, snapshot.asks)
        self.bids = {p:q for p,q in snapshot.bids if q > 0}
        self.asks = {p:q for p,q in snapshot.asks if q > 0}
        self.last_update_id = snapshot.last_update_id
        self.status = OrderBookStatus.SYNCHRONIZED
        self._buffer.clear()

    def apply_diff(self, diff: OrderBookDiff) -> None:
        if diff.first_update_id > diff.final_update_id:
            self.status = OrderBookStatus.RECOVERY_REQUIRED
            raise ValueError("INVALID_ORDERBOOK_UPDATE_RANGE")
        if self.last_update_id is None:
            self._buffer.append(diff)
            self.status = OrderBookStatus.RECOVERY_REQUIRED
            raise ValueError("ORDERBOOK_SNAPSHOT_REQUIRED")
        if diff.final_update_id <= self.last_update_id:
            return  # stale/duplicate event: no side effect
        if diff.first_update_id > self.last_update_id + 1:
            self.status = OrderBookStatus.GAP_DETECTED
            raise ValueError("ORDERBOOK_SEQUENCE_GAP")
        self._validate_levels(diff.bids, is_bid=True)
        self._validate_levels(diff.asks, is_bid=False)
        for p,q in diff.bids:
            if q == 0: self.bids.pop(p, None)
            else: self.bids[p] = q
        for p,q in diff.asks:
            if q == 0: self.asks.pop(p, None)
            else: self.asks[p] = q
        if self.best_bid() is not None and self.best_ask() is not None and self.best_bid() > self.best_ask():
            self.status = OrderBookStatus.RECOVERY_REQUIRED
            raise ValueError("CROSSED_ORDERBOOK")
        self.last_update_id = diff.final_update_id
        self.status = OrderBookStatus.SYNCHRONIZED

    def best_bid(self) -> Decimal | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> Decimal | None:
        return min(self.asks) if self.asks else None

    def spread(self) -> Decimal | None:
        b,a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else a-b

    @staticmethod
    def _validate_levels(levels: Iterable[tuple[Decimal,Decimal]], *, is_bid: bool) -> None:
        prev = None
        for p,q in levels:
            if p <= 0 or q < 0:
                raise ValueError("INVALID_ORDERBOOK_LEVEL")
            if prev is not None:
                if is_bid and p >= prev: raise ValueError("BID_LEVEL_ORDER_INVALID")
                if not is_bid and p <= prev: raise ValueError("ASK_LEVEL_ORDER_INVALID")
            prev = p

    @staticmethod
    def _validate_crossed(bids, asks) -> None:
        if bids and asks:
            if max(p for p,_ in bids) > min(p for p,_ in asks):
                raise ValueError("CROSSED_ORDERBOOK")

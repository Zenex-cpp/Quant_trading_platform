from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from trading_platform.execution.models import Fill
from trading_platform.v21.event_store import EventStore, LedgerEvent, sha256_json


class FillIdentityConflict(RuntimeError):
    """One venue fill identity was observed with incompatible economic content."""


@dataclass(frozen=True)
class FillAcceptance:
    identity_key: str
    event: LedgerEvent | None
    created: bool

    @property
    def event_hash(self) -> str | None:
        return self.event.event_hash if self.event else None


class DurableFillAuthority:
    """Durable exactly-once acceptance boundary for exchange fill identities.

    The authority uses venue/exchange-order/trade identity when available, so the same
    fill cannot be accepted twice merely because REST and user-stream adapters produce
    different local fill IDs. A conflicting reuse of the same venue identity fails closed.
    """

    EVENT_TYPE = "FILL_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def identity_key(fill: Fill) -> str:
        venue = (fill.venue or "UNKNOWN").upper()
        if fill.exchange_order_id and fill.trade_id:
            return f"{venue}:TRADE:{fill.exchange_order_id}:{fill.trade_id}"
        if fill.exchange_order_id and fill.fill_id:
            return f"{venue}:ORDER_FILL:{fill.exchange_order_id}:{fill.fill_id}"
        return f"LOCAL:{fill.fill_id}"

    @staticmethod
    def fingerprint(fill: Fill) -> str:
        payload = {
            "identity_key": DurableFillAuthority.identity_key(fill),
            "order_request_id": fill.order_request_id,
            "exchange_order_id": fill.exchange_order_id,
            "trade_id": fill.trade_id,
            "venue": fill.venue,
            "quantity": str(fill.quantity),
            "price": str(fill.price),
            "fee": str(fill.fee),
            "funding": str(fill.funding),
            "slippage": str(fill.slippage),
            "market_impact": str(fill.market_impact),
            "event_time": str(fill.event_time),
        }
        return sha256_json(payload)

    def accept(self, fill: Fill, *, occurred_at_ms: int) -> FillAcceptance:
        key = self.identity_key(fill)
        payload = {
            "identity_key": key,
            "fingerprint": self.fingerprint(fill),
        }
        event_id = "fill-identity:" + sha256(key.encode()).hexdigest()
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
                raise FillIdentityConflict("FILL_IDENTITY_REUSE_WITH_DIFFERENT_CONTENT")
            return FillAcceptance(key, existing, False)
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=occurred_at_ms,
            event_type=self.EVENT_TYPE,
            aggregate_id=fill.order_request_id,
            payload=payload,
        )
        return FillAcceptance(key, result.event, True)

    def accepted(self, fill: Fill) -> bool:
        key = self.identity_key(fill)
        event_id = "fill-identity:" + sha256(key.encode()).hexdigest()
        return self.store.get(event_id) is not None

    def assert_chain(self) -> None:
        if not self.store.verify_chain():
            raise RuntimeError("FILL_AUTHORITY_EVENT_CHAIN_INVALID")

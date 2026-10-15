from dataclasses import dataclass
from decimal import Decimal
from trading_platform.execution.models import Fill, Side

@dataclass(frozen=True)
class FillLedgerEntry:
    fill_id: str
    order_request_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    funding: Decimal

class FillLedger:
    def __init__(self) -> None:
        self._entries: dict[str, FillLedgerEntry] = {}
        self._by_identity: dict[str, str] = {}

    @staticmethod
    def identity_key(fill: Fill) -> str:
        venue = (fill.venue or "UNKNOWN").upper()
        if fill.exchange_order_id and fill.trade_id:
            return f"{venue}:TRADE:{fill.exchange_order_id}:{fill.trade_id}"
        if fill.exchange_order_id and fill.fill_id:
            return f"{venue}:ORDER_FILL:{fill.exchange_order_id}:{fill.fill_id}"
        return f"LOCAL:{fill.fill_id}"

    def apply_once(self, fill: Fill) -> tuple[FillLedgerEntry, bool]:
        if fill.quantity <= 0 or fill.price <= 0:
            raise ValueError("INVALID_FILL")
        identity = self.identity_key(fill)
        entry=FillLedgerEntry(fill.fill_id, fill.order_request_id, fill.quantity, fill.price, fill.fee, fill.funding)
        prior_fill_id = self._by_identity.get(identity)
        if prior_fill_id is not None:
            prior = self._entries[prior_fill_id]
            if (prior.order_request_id, prior.quantity, prior.price, prior.fee, prior.funding) != (entry.order_request_id, entry.quantity, entry.price, entry.fee, entry.funding):
                raise ValueError("FILL_IDENTITY_REUSE_WITH_DIFFERENT_CONTENT")
            return prior, False
        prior=self._entries.get(fill.fill_id)
        if prior is not None:
            if prior != entry:
                raise ValueError("FILL_ID_REUSE_WITH_DIFFERENT_CONTENT")
            self._by_identity[identity] = fill.fill_id
            return prior, False
        self._entries[fill.fill_id]=entry
        self._by_identity[identity]=fill.fill_id
        return entry, True

    def apply(self, fill: Fill) -> FillLedgerEntry:
        return self.apply_once(fill)[0]

    def total_quantity(self, order_request_id: str) -> Decimal:
        return sum((e.quantity for e in self._entries.values() if e.order_request_id==order_request_id), Decimal("0"))

    def entries(self):
        return tuple(self._entries.values())

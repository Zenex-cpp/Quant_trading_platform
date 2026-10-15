from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore, LedgerEvent, sha256_json


class AccountingReplayError(RuntimeError):
    pass


class AccountingConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class DurableFill:
    fill_id: str
    order_request_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    occurred_at_ms: int = 0
    exchange_order_id: str | None = None
    trade_id: str | None = None
    venue: str = "UNKNOWN"

    def payload(self) -> dict[str, str | int | None]:
        payload = {
            "fill_id": self.fill_id,
            "order_request_id": self.order_request_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "fee": str(self.fee),
            "funding": str(self.funding),
            "occurred_at_ms": self.occurred_at_ms,
            "exchange_order_id": self.exchange_order_id,
            "trade_id": self.trade_id,
            "venue": self.venue,
        }
        if self.exchange_order_id and self.trade_id:
            payload.pop("fill_id", None)
        return payload


@dataclass(frozen=True)
class PositionProjection:
    symbol: str
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")


@dataclass(frozen=True)
class AccountingProjection:
    cash: Decimal = Decimal("0")
    positions: tuple[PositionProjection, ...] = ()
    processed_event_ids: tuple[str, ...] = ()

    @property
    def realized_pnl(self) -> Decimal:
        return sum((p.realized_pnl for p in self.positions), Decimal("0"))

    @property
    def fees(self) -> Decimal:
        return sum((p.fees for p in self.positions), Decimal("0"))

    @property
    def funding(self) -> Decimal:
        return sum((p.funding for p in self.positions), Decimal("0"))

    def payload(self) -> dict[str, Any]:
        return {
            "cash": str(self.cash),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": str(p.quantity),
                    "avg_entry_price": str(p.avg_entry_price),
                    "realized_pnl": str(p.realized_pnl),
                    "fees": str(p.fees),
                    "funding": str(p.funding),
                }
                for p in self.positions
            ],
        }

    @property
    def state_hash(self) -> str:
        return sha256_json(self.payload())


@dataclass(frozen=True)
class ExchangeAccountingSnapshot:
    equity: Decimal
    positions: Mapping[str, Decimal]
    snapshot_id: str


@dataclass(frozen=True)
class AccountingReconciliation:
    reconstructed: AccountingProjection
    exchange: ExchangeAccountingSnapshot
    equity_expected: Decimal
    equity_tolerance: Decimal = Decimal("0.00000001")
    position_tolerance: Decimal = Decimal("0.00000001")

    @property
    def equity_delta(self) -> Decimal:
        return self.exchange.equity - self.equity_expected

    @property
    def position_deltas(self) -> dict[str, Decimal]:
        local = {p.symbol: p.quantity for p in self.reconstructed.positions}
        symbols = set(local) | set(self.exchange.positions)
        return {s: self.exchange.positions.get(s, Decimal("0")) - local.get(s, Decimal("0")) for s in sorted(symbols)}

    @property
    def positions_match(self) -> bool:
        return all(abs(v) <= self.position_tolerance for v in self.position_deltas.values())

    @property
    def equity_match(self) -> bool:
        return abs(self.equity_delta) <= self.equity_tolerance

    @property
    def reconciled(self) -> bool:
        return self.equity_match and self.positions_match


class DurableAccountingLedger:
    """Append-only fill/funding/cash ledger with deterministic restart reconstruction."""

    FILL = "ACCOUNTING_FILL"
    FUNDING = "ACCOUNTING_FUNDING"
    CASH_ADJUSTMENT = "ACCOUNTING_CASH_ADJUSTMENT"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def fill_identity(fill: DurableFill) -> str:
        venue = (fill.venue or "UNKNOWN").upper()
        if fill.exchange_order_id and fill.trade_id:
            return f"{venue}:TRADE:{fill.exchange_order_id}:{fill.trade_id}"
        if fill.exchange_order_id and fill.fill_id:
            return f"{venue}:ORDER_FILL:{fill.exchange_order_id}:{fill.fill_id}"
        return f"LOCAL:{fill.fill_id}"

    @staticmethod
    def _semantic_fill_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in dict(payload).items() if k not in {"fill_id", "occurred_at_ms"}}

    def append_fill_once(self, fill: DurableFill) -> tuple[LedgerEvent, bool]:
        self._validate_fill(fill)
        event_id=(f"fill:{fill.fill_id}" if not (fill.exchange_order_id and fill.trade_id) else f"fill:{self.fill_identity(fill)}")
        existing=self.store.get(event_id)
        payload=fill.payload()
        if existing is not None:
            if existing.event_type != self.FILL or str(existing.aggregate_id) != fill.symbol or self._semantic_fill_payload(existing.payload) != self._semantic_fill_payload(payload):
                raise AccountingConflict("EVENT_ID_REUSE_WITH_DIFFERENT_CONTENT")
            return existing, False
        event=self._append(
            event_id=event_id,
            event_type=self.FILL,
            aggregate_id=fill.symbol,
            occurred_at_ms=fill.occurred_at_ms,
            payload=payload,
        )
        return event, True

    def append_fill(self, fill: DurableFill) -> LedgerEvent:
        return self.append_fill_once(fill)[0]

    def append_funding(self, *, event_id: str, symbol: str, amount: Decimal, occurred_at_ms: int) -> LedgerEvent:
        self._validate_amount(amount)
        return self._append(event_id=f"funding:{event_id}", event_type=self.FUNDING,
                            aggregate_id=symbol, occurred_at_ms=occurred_at_ms,
                            payload={"amount": str(amount), "symbol": symbol})

    def append_cash_adjustment(self, *, event_id: str, amount: Decimal, occurred_at_ms: int, reason: str) -> LedgerEvent:
        self._validate_amount(amount)
        if not reason:
            raise ValueError("MISSING_CASH_ADJUSTMENT_REASON")
        return self._append(event_id=f"cash:{event_id}", event_type=self.CASH_ADJUSTMENT,
                            aggregate_id="ACCOUNT", occurred_at_ms=occurred_at_ms,
                            payload={"amount": str(amount), "reason": reason})

    def reconstruct(self) -> AccountingProjection:
        if not self.store.verify_chain():
            raise AccountingReplayError("EVENT_CHAIN_INVALID")
        state = AccountingProjection()
        seen: set[str] = set()
        for event in self.store.iter_events():
            if event.event_id in seen:
                raise AccountingReplayError("DUPLICATE_EVENT_IN_REPLAY")
            state = self._apply(state, event)
            seen.add(event.event_id)
        return AccountingProjection(state.cash, state.positions, tuple(sorted(seen)))

    def append_and_reconstruct_fill(self, fill: DurableFill) -> AccountingProjection:
        self.append_fill(fill)
        return self.reconstruct()

    @staticmethod
    def _validate_amount(amount: Decimal) -> None:
        if not amount.is_finite():
            raise ValueError("NON_FINITE_ACCOUNTING_AMOUNT")

    @classmethod
    def _validate_fill(cls, fill: DurableFill) -> None:
        if not fill.fill_id or not fill.order_request_id or not fill.symbol:
            raise ValueError("INVALID_FILL_IDENTITY")
        if fill.side.upper() not in {"BUY", "SELL"}:
            raise ValueError("INVALID_FILL_SIDE")
        if fill.quantity <= 0 or fill.price <= 0:
            raise ValueError("INVALID_FILL")
        cls._validate_amount(fill.quantity)
        cls._validate_amount(fill.price)
        cls._validate_amount(fill.fee)
        cls._validate_amount(fill.funding)
        if fill.occurred_at_ms < 0:
            raise ValueError("INVALID_FILL_TIMESTAMP")
        if not fill.venue:
            raise ValueError("INVALID_FILL_VENUE")
        if fill.exchange_order_id is not None and not str(fill.exchange_order_id):
            raise ValueError("INVALID_EXCHANGE_ORDER_ID")
        if fill.trade_id is not None and not str(fill.trade_id):
            raise ValueError("INVALID_TRADE_ID")

    def _append(self, *, event_id: str, event_type: str, aggregate_id: str,
                occurred_at_ms: int, payload: Mapping[str, Any]) -> LedgerEvent:
        existing = self.store.get(event_id)
        result = self.store.append(event_id=event_id, occurred_at_ms=occurred_at_ms,
                                   event_type=event_type, aggregate_id=aggregate_id, payload=payload)
        if result.duplicate and existing is not None and (existing.event_type != event_type or dict(existing.payload) != dict(payload)):
            raise AccountingConflict("EVENT_ID_REUSE_WITH_DIFFERENT_CONTENT")
        return result.event

    @classmethod
    def _apply(cls, state: AccountingProjection, event: LedgerEvent) -> AccountingProjection:
        positions = {p.symbol: p for p in state.positions}
        cash = state.cash
        if event.event_type == cls.FILL:
            p = event.payload
            side = str(p["side"]).upper()
            qty = Decimal(str(p["quantity"]))
            price = Decimal(str(p["price"]))
            fee = Decimal(str(p.get("fee", "0")))
            funding = Decimal(str(p.get("funding", "0")))
            if qty <= 0 or price <= 0 or side not in {"BUY", "SELL"}:
                raise AccountingReplayError("INVALID_PERSISTED_FILL")
            prior = positions.get(str(p["symbol"]), PositionProjection(str(p["symbol"])))
            signed = qty if side == "BUY" else -qty
            old_q = prior.quantity
            new_q = old_q + signed
            realized = prior.realized_pnl
            avg = prior.avg_entry_price
            if old_q == 0 or (old_q > 0 and signed > 0) or (old_q < 0 and signed < 0):
                total = abs(old_q) + abs(signed)
                avg = ((abs(old_q) * avg) + (abs(signed) * price)) / total
            else:
                closing = min(abs(old_q), abs(signed))
                direction = Decimal("1") if old_q > 0 else Decimal("-1")
                realized += closing * (price - avg) * direction
                if new_q == 0:
                    avg = Decimal("0")
                elif (old_q > 0 and new_q < 0) or (old_q < 0 and new_q > 0):
                    avg = price
            positions[str(p["symbol"])] = PositionProjection(
                str(p["symbol"]), new_q, avg, realized, prior.fees + fee, prior.funding + funding
            )
            # Fee/funding reduce cash in the projection; realized P&L is not booked to cash here.
            cash -= fee
            cash += funding
        elif event.event_type == cls.FUNDING:
            amount = Decimal(str(event.payload.get("amount", "0")))
            cash += amount
            symbol = str(event.payload.get("symbol", event.aggregate_id))
            prior = positions.get(symbol, PositionProjection(symbol))
            positions[symbol] = PositionProjection(symbol, prior.quantity, prior.avg_entry_price,
                                                    prior.realized_pnl, prior.fees, prior.funding + amount)
        elif event.event_type == cls.CASH_ADJUSTMENT:
            cash += Decimal(str(event.payload.get("amount", "0")))
        else:
            raise AccountingReplayError(f"UNSUPPORTED_ACCOUNTING_EVENT:{event.event_type}")
        return AccountingProjection(cash, tuple(positions[k] for k in sorted(positions)), state.processed_event_ids + (event.event_id,))


class RestartSafeAccountingRegistry:
    def __init__(self, ledger: DurableAccountingLedger) -> None:
        self.ledger = ledger
        self._state: AccountingProjection | None = None

    def restore(self) -> AccountingProjection:
        self._state = self.ledger.reconstruct()
        return self._state

    def current(self) -> AccountingProjection:
        if self._state is None:
            return self.restore()
        return self._state


@dataclass(frozen=True)
class RecoveryProof:
    state_hash: str
    event_chain_verified: bool
    replay_succeeded: bool
    positions_finite: bool

    @property
    def passed(self) -> bool:
        return self.event_chain_verified and self.replay_succeeded and self.positions_finite


def prove_recovery(ledger: DurableAccountingLedger) -> tuple[AccountingProjection, RecoveryProof]:
    chain_ok = ledger.store.verify_chain()
    if not chain_ok:
        proof = RecoveryProof("", False, False, False)
        raise AccountingReplayError("EVENT_CHAIN_INVALID")
    try:
        state = ledger.reconstruct()
        finite = all(v.is_finite() for p in state.positions for v in (p.quantity, p.avg_entry_price, p.realized_pnl, p.fees, p.funding)) and state.cash.is_finite()
    except Exception:
        proof = RecoveryProof("", True, False, False)
        raise
    proof = RecoveryProof(state.state_hash, True, True, finite)
    if not proof.passed:
        raise AccountingReplayError("RECOVERY_PROOF_FAILED")
    return state, proof

"""V3.80 Binance USDⓈ-M private user-data projection and REST/WS reconciliation.

The module deliberately separates three concerns:

1. private WebSocket URL routing;
2. user-data event normalization/projection with deterministic ordering/deduplication;
3. REST vs user-stream reconciliation as a trading gate.

It does not open a socket itself. Network transport remains injected through the
existing WebSocket runtime contract. This keeps testnet connectivity and mutation
permissions outside the projection state machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from trading_platform.v20.reconciliation import RestWebSocketReconciler, ReconciliationResult
from trading_platform.v19.user_stream import UserEventType


class UserDataHealth(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    GAP_SUSPECTED = "GAP_SUSPECTED"
    UNKNOWN = "UNKNOWN"


class UserDataApplyReason(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    LISTEN_KEY_EXPIRED = "LISTEN_KEY_EXPIRED"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"
    MALFORMED_EVENT = "MALFORMED_EVENT"
    STREAM_BLOCKED = "STREAM_BLOCKED"


@dataclass(frozen=True)
class BinancePrivateWebSocketConfig:
    """Current routed Binance USDⓈ-M Futures private WebSocket endpoints."""

    environment: str = "TESTNET"
    mode: str = "ws"

    def base_url(self) -> str:
        if self.environment == "TESTNET":
            return "wss://stream.binancefuture.com/private"
        if self.environment == "PRODUCTION":
            return "wss://fstream.binance.com/private"
        raise ValueError("UNSUPPORTED_BINANCE_ENVIRONMENT")

    def url(self, *, listen_key: str, events: Sequence[str] | None = None) -> str:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        if self.mode != "ws":
            raise ValueError("ONLY_WS_PRIVATE_MODE_SUPPORTED")
        base = self.base_url().rstrip("/") + "/ws"
        if events:
            clean = [str(e).strip().upper() for e in events if str(e).strip()]
            if not clean:
                raise ValueError("EVENT_FILTER_REQUIRED")
            query: list[tuple[str, str]] = [("listenKey", listen_key)]
            query.extend(("events", event) for event in clean)
            return base + "?" + urlencode(query)
        return base + "/" + listen_key


@dataclass(frozen=True)
class ProjectedOrder:
    client_order_id: str | None
    exchange_order_id: str
    symbol: str
    status: str
    execution_type: str | None
    original_quantity: Decimal
    cumulative_filled_quantity: Decimal
    average_price: Decimal
    last_fill_quantity: Decimal
    last_fill_price: Decimal
    trade_id: str | None
    event_time_ms: int | None
    transaction_time_ms: int | None
    raw_hash: str


@dataclass(frozen=True)
class ProjectedPosition:
    symbol: str
    position_side: str
    quantity: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    update_time_ms: int | None


@dataclass(frozen=True)
class UserDataApplyResult:
    accepted: bool
    duplicate: bool
    changed: bool
    health: UserDataHealth
    reason: UserDataApplyReason
    event_type: str
    raw_hash: str


@dataclass(frozen=True)
class UserDataProjectionSnapshot:
    health: UserDataHealth
    last_event_time_ms: int | None
    orders: tuple[ProjectedOrder, ...]
    positions: tuple[ProjectedPosition, ...]
    seen_event_count: int
    seen_trade_count: int
    state_hash: str

    @property
    def trading_allowed(self) -> bool:
        return self.health is UserDataHealth.HEALTHY


_TERMINAL_ORDER_STATES = {
    "FILLED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
}


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _event_type(payload: Mapping[str, Any]) -> str:
    return str(payload.get("e", "UNKNOWN"))


class BinanceUserDataProjection:
    """Deterministic in-memory projection for Binance private user-data events.

    Ordering is enforced per event type using (T, E), matching Binance's documented
    same-event-type ordering guarantee. A violation is fail-closed and blocks trading.
    Trade events are deduplicated by (exchange_order_id, trade_id); non-trade events
    are deduplicated by canonical raw-event hash.
    """

    def __init__(self, *, stale_after_seconds: int = 90) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("INVALID_STALE_AFTER_SECONDS")
        self.stale_after_seconds = stale_after_seconds
        self.health = UserDataHealth.UNKNOWN
        self.last_event_time_ms: int | None = None
        self._last_by_type: dict[str, tuple[int, int]] = {}
        self._seen_hashes: set[str] = set()
        self._seen_trades: set[str] = set()
        self._orders: dict[str, ProjectedOrder] = {}
        self._positions: dict[tuple[str, str], ProjectedPosition] = {}
        self._event_count = 0

    def start(self) -> None:
        self.health = UserDataHealth.HEALTHY

    def _order_record(self, payload: Mapping[str, Any], raw_hash: str) -> ProjectedOrder:
        o = payload.get("o") if isinstance(payload.get("o"), Mapping) else None
        if not o or o.get("i") is None or o.get("s") is None:
            raise ValueError("ORDER_TRADE_UPDATE_MALFORMED")
        return ProjectedOrder(
            client_order_id=str(o.get("c")) if o.get("c") is not None else None,
            exchange_order_id=str(o.get("i")),
            symbol=str(o.get("s")),
            status=str(o.get("X", "UNKNOWN")).upper(),
            execution_type=str(o.get("x")).upper() if o.get("x") is not None else None,
            original_quantity=_decimal(o.get("q")),
            cumulative_filled_quantity=_decimal(o.get("z")),
            average_price=_decimal(o.get("ap")),
            last_fill_quantity=_decimal(o.get("l")),
            last_fill_price=_decimal(o.get("L")),
            trade_id=str(o.get("t")) if o.get("t") is not None else None,
            event_time_ms=_int(payload.get("E")),
            transaction_time_ms=_int(payload.get("T")),
            raw_hash=raw_hash,
        )

    def _apply_positions(self, payload: Mapping[str, Any]) -> bool:
        account = payload.get("a") if isinstance(payload.get("a"), Mapping) else None
        if not account:
            raise ValueError("ACCOUNT_UPDATE_MALFORMED")
        changed = False
        for p in account.get("P", []) or []:
            if not isinstance(p, Mapping) or p.get("s") is None:
                continue
            symbol = str(p.get("s"))
            side = str(p.get("ps", "BOTH"))
            record = ProjectedPosition(
                symbol=symbol,
                position_side=side,
                quantity=_decimal(p.get("pa")),
                entry_price=_decimal(p.get("ep")),
                unrealized_pnl=_decimal(p.get("up")),
                update_time_ms=_int(payload.get("T")),
            )
            self._positions[(symbol, side)] = record
            changed = True
        return changed

    def apply(self, payload: Mapping[str, Any], *, now_epoch: float | None = None) -> UserDataApplyResult:
        if not isinstance(payload, Mapping):
            return UserDataApplyResult(False, False, False, UserDataHealth.UNKNOWN, UserDataApplyReason.MALFORMED_EVENT, "UNKNOWN", "")
        raw_hash = _hash(payload)
        event_type = _event_type(payload)
        if raw_hash in self._seen_hashes:
            return UserDataApplyResult(True, True, False, self.health, UserDataApplyReason.DUPLICATE, event_type, raw_hash)

        if event_type == UserEventType.LISTEN_KEY_EXPIRED.value:
            self._seen_hashes.add(raw_hash)
            self.health = UserDataHealth.EXPIRED
            self._event_count += 1
            return UserDataApplyResult(True, False, True, self.health, UserDataApplyReason.LISTEN_KEY_EXPIRED, event_type, raw_hash)

        if event_type not in {
            UserEventType.ORDER_TRADE_UPDATE.value,
            UserEventType.ACCOUNT_UPDATE.value,
            UserEventType.ACCOUNT_CONFIG_UPDATE.value,
            UserEventType.MARGIN_CALL.value,
        }:
            self._seen_hashes.add(raw_hash)
            if self.health is UserDataHealth.UNKNOWN:
                self.health = UserDataHealth.GAP_SUSPECTED
            return UserDataApplyResult(False, False, False, self.health, UserDataApplyReason.UNKNOWN_EVENT, event_type, raw_hash)

        event_time = _int(payload.get("E"))
        transaction_time = _int(payload.get("T"))
        if event_time is None:
            self.health = UserDataHealth.GAP_SUSPECTED
            return UserDataApplyResult(False, False, False, self.health, UserDataApplyReason.MALFORMED_EVENT, event_type, raw_hash)
        prior = self._last_by_type.get(event_type)
        current_key = (transaction_time if transaction_time is not None else -1, event_time)
        if prior is not None and current_key < prior:
            self._seen_hashes.add(raw_hash)
            self.health = UserDataHealth.GAP_SUSPECTED
            return UserDataApplyResult(False, False, False, self.health, UserDataApplyReason.OUT_OF_ORDER, event_type, raw_hash)

        self._seen_hashes.add(raw_hash)
        self._last_by_type[event_type] = current_key
        self.last_event_time_ms = max(self.last_event_time_ms or event_time, event_time)
        self._event_count += 1
        changed = False

        if event_type == UserEventType.ORDER_TRADE_UPDATE.value:
            record = self._order_record(payload, raw_hash)
            if record.execution_type == "TRADE" and record.trade_id not in (None, "0"):
                trade_key = f"TRADE:{record.exchange_order_id}:{record.trade_id}"
                if trade_key in self._seen_trades:
                    return UserDataApplyResult(True, True, False, self.health, UserDataApplyReason.DUPLICATE, event_type, raw_hash)
                self._seen_trades.add(trade_key)
            self._orders[record.exchange_order_id] = record
            changed = True
        elif event_type == UserEventType.ACCOUNT_UPDATE.value:
            changed = self._apply_positions(payload)
        else:
            # CONFIG/MARGIN events are operationally relevant but do not alter the
            # order/position projection represented by this module.
            changed = True

        if self.health is UserDataHealth.UNKNOWN:
            self.health = UserDataHealth.HEALTHY
        if now_epoch is not None:
            self.refresh_health(now_epoch)
        return UserDataApplyResult(True, False, changed, self.health, UserDataApplyReason.ACCEPTED, event_type, raw_hash)

    def refresh_health(self, now_epoch: float) -> UserDataHealth:
        if self.health in {UserDataHealth.EXPIRED, UserDataHealth.GAP_SUSPECTED}:
            return self.health
        if self.last_event_time_ms is None:
            self.health = UserDataHealth.STALE
            return self.health
        age = now_epoch - (self.last_event_time_ms / 1000.0)
        if age > self.stale_after_seconds:
            self.health = UserDataHealth.STALE
        elif self.health in {UserDataHealth.UNKNOWN, UserDataHealth.STALE}:
            self.health = UserDataHealth.HEALTHY
        return self.health

    def account_snapshot(self) -> dict[str, Any]:
        open_orders = []
        for record in self._orders.values():
            if record.status in _TERMINAL_ORDER_STATES:
                continue
            open_orders.append({
                "orderId": record.exchange_order_id,
                "clientOrderId": record.client_order_id,
                "symbol": record.symbol,
                "status": record.status,
                "executedQty": str(record.cumulative_filled_quantity),
                "avgPrice": str(record.average_price),
                "eventTime": record.event_time_ms,
            })
        positions = [
            {
                "symbol": p.symbol,
                "positionAmt": str(p.quantity),
                "entryPrice": str(p.entry_price),
                "unrealizedProfit": str(p.unrealized_pnl),
                "positionSide": p.position_side,
                "updateTime": p.update_time_ms,
            }
            for p in self._positions.values()
        ]
        return {"openOrders": sorted(open_orders, key=lambda x: str(x["orderId"])),
                "positions": sorted(positions, key=lambda x: (x["symbol"], x["positionSide"]))}

    def reconcile(self, rest_account: Mapping[str, Any], *, now_epoch: float) -> ReconciliationResult:
        self.refresh_health(now_epoch)
        return RestWebSocketReconciler().reconcile(
            rest_account=rest_account,
            stream_account=self.account_snapshot(),
            stream_healthy=self.health is UserDataHealth.HEALTHY,
            stream_stale=self.health is UserDataHealth.STALE,
        )

    def snapshot(self, *, now_epoch: float | None = None) -> UserDataProjectionSnapshot:
        if now_epoch is not None:
            self.refresh_health(now_epoch)
        orders = tuple(sorted(self._orders.values(), key=lambda x: x.exchange_order_id))
        positions = tuple(sorted(self._positions.values(), key=lambda x: (x.symbol, x.position_side)))
        state = {
            "health": self.health.value,
            "last_event_time_ms": self.last_event_time_ms,
            "orders": [o.__dict__ for o in orders],
            "positions": [p.__dict__ for p in positions],
            "seen_event_count": self._event_count,
            "seen_trade_count": len(self._seen_trades),
        }
        return UserDataProjectionSnapshot(
            health=self.health,
            last_event_time_ms=self.last_event_time_ms,
            orders=orders,
            positions=positions,
            seen_event_count=self._event_count,
            seen_trade_count=len(self._seen_trades),
            state_hash=_hash(state),
        )

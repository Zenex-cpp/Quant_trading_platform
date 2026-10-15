from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
import hashlib, json

from trading_platform.v17.evidence import canonical_json, utc_now

class UserEventType(str, Enum):
    ORDER_TRADE_UPDATE = "ORDER_TRADE_UPDATE"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    ACCOUNT_CONFIG_UPDATE = "ACCOUNT_CONFIG_UPDATE"
    MARGIN_CALL = "MARGIN_CALL"
    LISTEN_KEY_EXPIRED = "listenKeyExpired"
    UNKNOWN = "UNKNOWN"

class StreamHealth(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    GAP_SUSPECTED = "GAP_SUSPECTED"

@dataclass(frozen=True)
class NormalizedUserEvent:
    event_type: UserEventType
    event_time_ms: int | None
    transaction_time_ms: int | None
    order_id: str | None
    symbol: str | None
    order_status: str | None
    execution_type: str | None
    raw_hash: str
    payload: Mapping[str, Any]

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.event_time_ms or -1, self.transaction_time_ms or -1)


def _i(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def normalize_user_event(payload: Mapping[str, Any]) -> NormalizedUserEvent:
    et = str(payload.get("e", "UNKNOWN"))
    try:
        event_type = UserEventType(et)
    except ValueError:
        event_type = UserEventType.UNKNOWN
    order = payload.get("o") if isinstance(payload.get("o"), Mapping) else {}
    raw_hash = hashlib.sha256(canonical_json(payload)).hexdigest()
    return NormalizedUserEvent(
        event_type=event_type,
        event_time_ms=_i(payload.get("E")),
        transaction_time_ms=_i(payload.get("T")),
        order_id=str(order.get("i")) if order.get("i") is not None else None,
        symbol=str(order.get("s")) if order.get("s") is not None else None,
        order_status=str(order.get("X")) if order.get("X") is not None else None,
        execution_type=str(order.get("x")) if order.get("x") is not None else None,
        raw_hash=raw_hash,
        payload=dict(payload),
    )

class UserStreamSequencer:
    """Monotonic event guard. It fails closed on stale or out-of-order events for the same stream."""
    def __init__(self) -> None:
        self.last_sort_key: tuple[int, int] | None = None
        self.health = StreamHealth.HEALTHY
        self.accepted = 0
        self.rejected = 0

    def accept(self, event: NormalizedUserEvent) -> bool:
        if event.event_type is UserEventType.LISTEN_KEY_EXPIRED:
            self.health = StreamHealth.EXPIRED
            self.rejected += 1
            return False
        key = event.sort_key
        if self.last_sort_key is not None and key < self.last_sort_key:
            self.health = StreamHealth.GAP_SUSPECTED
            self.rejected += 1
            return False
        self.last_sort_key = key
        self.accepted += 1
        return True

@dataclass(frozen=True)
class KeepalivePolicy:
    stream_ttl_seconds: int = 3600
    keepalive_seconds: int = 3300
    stale_after_seconds: int = 90

    def validate(self) -> None:
        if self.stream_ttl_seconds <= 0 or self.keepalive_seconds <= 0:
            raise ValueError("INVALID_KEEPALIVE_POLICY")
        if self.keepalive_seconds >= self.stream_ttl_seconds:
            raise ValueError("KEEPALIVE_MUST_PRECEDE_EXPIRY")
        if self.stale_after_seconds <= 0:
            raise ValueError("INVALID_STALE_THRESHOLD")

@dataclass(frozen=True)
class UserStreamState:
    health: StreamHealth
    listen_key_present: bool
    last_event_time_ms: int | None
    next_keepalive_due_epoch: float | None

class UserStreamMonitor:
    def __init__(self, policy: KeepalivePolicy = KeepalivePolicy()) -> None:
        policy.validate()
        self.policy = policy
        self.listen_key_present = False
        self.last_event_time_ms: int | None = None
        self.started_epoch: float | None = None
        self.health = StreamHealth.HEALTHY

    def started(self, now_epoch: float, listen_key: str) -> None:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        self.listen_key_present = True
        self.started_epoch = float(now_epoch)
        self.last_event_time_ms = None
        self.health = StreamHealth.HEALTHY

    def observe(self, event: NormalizedUserEvent) -> None:
        self.last_event_time_ms = event.event_time_ms
        if event.event_type is UserEventType.LISTEN_KEY_EXPIRED:
            self.health = StreamHealth.EXPIRED
            self.listen_key_present = False

    def state(self, now_epoch: float) -> UserStreamState:
        if not self.listen_key_present:
            return UserStreamState(StreamHealth.EXPIRED if self.started_epoch is not None else self.health, False,
                                    self.last_event_time_ms, None)
        due = (self.started_epoch or now_epoch) + self.policy.keepalive_seconds
        if self.last_event_time_ms is not None:
            age = now_epoch - self.last_event_time_ms / 1000.0
            if age > self.policy.stale_after_seconds:
                self.health = StreamHealth.STALE
        if now_epoch >= due:
            self.health = StreamHealth.STALE
        return UserStreamState(self.health, True, self.last_event_time_ms, due)

    def require_healthy_for_trading(self, now_epoch: float) -> None:
        if self.state(now_epoch).health is not StreamHealth.HEALTHY:
            raise PermissionError("USER_STREAM_NOT_HEALTHY")

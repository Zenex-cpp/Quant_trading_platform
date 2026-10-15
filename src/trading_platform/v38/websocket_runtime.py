from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Callable, Mapping, Protocol

from trading_platform.v37.user_stream_runtime import (
    RecoveryAssessment,
    SessionState,
    UserStreamRuntimeState,
    UserStreamSessionCoordinator,
)


class SocketState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class SocketTransport(Protocol):
    def connect(self, url: str) -> None: ...
    def send(self, payload: str) -> None: ...
    def recv(self, timeout_s: float) -> str | None: ...
    def close(self) -> None: ...


class UserStreamControl(Protocol):
    def start(self) -> str: ...
    def ping(self, listen_key: str) -> None: ...


@dataclass(frozen=True)
class WebSocketConfig:
    url: str = "wss://stream.binance.com/ws"
    heartbeat_interval_s: float = 30.0
    recv_timeout_s: float = 5.0
    reconnect_backoff_s: float = 1.0

    def validate(self) -> None:
        if not self.url.startswith("wss://"):
            raise ValueError("TLS_WEBSOCKET_REQUIRED")
        if not self.heartbeat_interval_s > 0:
            raise ValueError("HEARTBEAT_INTERVAL_REQUIRED")
        if not self.recv_timeout_s > 0:
            raise ValueError("RECV_TIMEOUT_REQUIRED")
        if not self.reconnect_backoff_s > 0:
            raise ValueError("RECONNECT_BACKOFF_REQUIRED")


@dataclass(frozen=True)
class WebSocketSnapshot:
    socket_state: SocketState
    session_state: SessionState
    listen_key_present: bool
    trading_allowed: bool
    reconnect_required: bool
    last_ping_epoch: float | None
    reason: str


class BinanceUserStreamRuntime:
    """Network-injected WebSocket runtime; default behavior is network-free in tests.

    The runtime never re-enables trading merely because the socket reconnects. V3.7's
    REST reconciliation gate remains authoritative.
    """

    def __init__(
        self,
        *,
        coordinator: UserStreamSessionCoordinator,
        transport: SocketTransport,
        config: WebSocketConfig = WebSocketConfig(),
        clock: Callable[[], float] = time.time,
    ) -> None:
        config.validate()
        self.coordinator = coordinator
        self.transport = transport
        self.config = config
        self.clock = clock
        self.socket_state = SocketState.DISCONNECTED
        self.last_ping_epoch: float | None = None
        self.reason = "INITIAL"
        self.reconnect_required = False

    def start(self, *, listen_key: str, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        self.socket_state = SocketState.CONNECTING
        self.reason = "CONNECTING"
        self.coordinator.start(listen_key=listen_key, now_epoch=now)
        try:
            self.transport.connect(self.config.url)
        except Exception:
            self.socket_state = SocketState.CLOSED
            self.reconnect_required = True
            self.coordinator.disconnected(now_epoch=now)
            self.reason = "CONNECT_FAILED"
            raise
        self.socket_state = SocketState.OPEN
        self.reconnect_required = False
        self.reason = "SOCKET_OPEN"
        return self.snapshot(now)

    def on_disconnect(self, *, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        self.socket_state = SocketState.CLOSED
        self.reconnect_required = True
        self.coordinator.disconnected(now_epoch=now)
        self.reason = "DISCONNECTED"
        return self.snapshot(now)

    def reconnect(self, *, listen_key: str, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        if not self.reconnect_required:
            raise ValueError("RECONNECT_NOT_REQUIRED")
        self.socket_state = SocketState.CONNECTING
        self.coordinator.connected_after_reconnect(listen_key=listen_key, now_epoch=now)
        try:
            self.transport.connect(self.config.url)
        except Exception:
            self.socket_state = SocketState.CLOSED
            self.reason = "RECONNECT_CONNECT_FAILED"
            return self.snapshot(now)
        self.socket_state = SocketState.OPEN
        self.reason = "RECONNECTED_REQUIRES_RECONCILIATION"
        return self.snapshot(now)

    def keepalive(self, control: UserStreamControl, *, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        if self.socket_state is not SocketState.OPEN:
            raise PermissionError("SOCKET_NOT_OPEN")
        listen_key = self.coordinator.listen_key
        if not listen_key:
            raise PermissionError("LISTEN_KEY_REQUIRED")
        control.ping(listen_key)
        self.last_ping_epoch = now
        self.coordinator.keepalive_succeeded(listen_key=listen_key, now_epoch=now)
        self.reason = "KEEPALIVE_OK"
        return self.snapshot(now)

    def receive(self, payload: Mapping[str, object], *, now_epoch: float | None = None):
        now = self.clock() if now_epoch is None else now_epoch
        if self.socket_state is not SocketState.OPEN:
            raise PermissionError("SOCKET_NOT_OPEN")
        result = self.coordinator.observe(payload, now_epoch=now)
        self.reason = result.reason or "EVENT_ACCEPTED"
        return result

    def run_recovery(self, recovery: Callable, *, now_epoch: float | None = None) -> UserStreamRuntimeState:
        now = self.clock() if now_epoch is None else now_epoch
        snapshot = self.coordinator.recover_with(recovery, now_epoch=now)
        if snapshot.trading_allowed:
            self.reconnect_required = False
            self.reason = "RECOVERY_VERIFIED"
        else:
            self.reason = snapshot.reason
        return snapshot

    def close(self, *, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        if self.socket_state not in {SocketState.CLOSED, SocketState.DISCONNECTED}:
            self.socket_state = SocketState.CLOSING
            try:
                self.transport.close()
            finally:
                self.socket_state = SocketState.CLOSED
        self.coordinator.close(now_epoch=now)
        self.reconnect_required = True
        self.reason = "CLOSED"
        return self.snapshot(now)

    def snapshot(self, now_epoch: float | None = None) -> WebSocketSnapshot:
        now = self.clock() if now_epoch is None else now_epoch
        session = self.coordinator.snapshot(now)
        return WebSocketSnapshot(
            socket_state=self.socket_state,
            session_state=session.state,
            listen_key_present=session.listen_key_present,
            trading_allowed=session.trading_allowed and self.socket_state is SocketState.OPEN,
            reconnect_required=self.reconnect_required or session.recovery_required,
            last_ping_epoch=self.last_ping_epoch,
            reason=self.reason,
        )

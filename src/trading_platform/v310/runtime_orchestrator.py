from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from trading_platform.v37.user_stream_runtime import (
    RecoveryAssessment,
    RecoveryCause,
    SessionState,
    UserStreamSessionCoordinator,
)
from trading_platform.v38.websocket_runtime import BinanceUserStreamRuntime, SocketState
from trading_platform.v39.binance_user_data_control import (
    BinanceUserDataControl,
    ControlResponseError,
    ControlTransportError,
    ControlPlaneSnapshot,
    RuntimeCredential,
)


class OrchestrationState(str, Enum):
    NEW = "NEW"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    KEEPALIVE_FAILED = "KEEPALIVE_FAILED"
    RECONNECTING = "RECONNECTING"
    RECOVERING = "RECOVERING"
    BLOCKED = "BLOCKED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class RuntimeCycleSnapshot:
    state: OrchestrationState
    session_state: SessionState
    socket_state: SocketState
    listen_key_present: bool
    trading_allowed: bool
    keepalive_due: bool
    recovery_required: bool
    last_action: str
    failure_count: int
    reason: str


class V310RuntimeOrchestrator:
    """Single-thread-friendly supervisor for the complete Binance user-data lifecycle.

    Safety contract:
    - only explicit successful control-plane responses can establish/refresh a listenKey;
    - keepalive failure immediately removes trading permission;
    - every reconnect enters RECOVERING and requires a REST reconciliation proof;
    - scheduler behavior is exposed as tick(), so production scheduling can be supplied
      externally and tests never need actual sleeps or network access.
    """

    def __init__(
        self,
        *,
        coordinator: UserStreamSessionCoordinator,
        control: BinanceUserDataControl,
        websocket: BinanceUserStreamRuntime,
        recovery: Callable[[RecoveryCause], RecoveryAssessment],
    ) -> None:
        if websocket.coordinator is not coordinator:
            raise ValueError("COORDINATOR_MISMATCH")
        if control.config.keepalive_interval_s <= 0:
            raise ValueError("KEEPALIVE_INTERVAL_REQUIRED")
        self.coordinator = coordinator
        self.control = control
        self.websocket = websocket
        self.recovery = recovery
        self.state = OrchestrationState.NEW
        self.failure_count = 0
        self.last_action = "INITIAL"
        self.reason = "INITIAL"
        self._next_keepalive_epoch: float | None = None

    def start(self, *, credential: RuntimeCredential, now_epoch: float) -> RuntimeCycleSnapshot:
        if self.state not in {OrchestrationState.NEW, OrchestrationState.STOPPED}:
            raise ValueError("ALREADY_STARTED")
        self.state = OrchestrationState.STARTING
        try:
            key = self.control.start(credential)
            self.websocket.start(listen_key=key, now_epoch=now_epoch)
        except Exception as exc:
            self.failure_count += 1
            self.state = OrchestrationState.BLOCKED
            self.last_action = "START_FAILED"
            self.reason = type(exc).__name__
            return self.snapshot(now_epoch)
        self._next_keepalive_epoch = now_epoch + self.control.config.keepalive_interval_s
        self.state = OrchestrationState.ACTIVE
        self.last_action = "START_OK"
        self.reason = "START_CONNECT_OK"
        return self.snapshot(now_epoch)

    def tick(self, *, credential: RuntimeCredential, now_epoch: float) -> RuntimeCycleSnapshot:
        """Run at most one deterministic control-plane action."""
        if self.state in {OrchestrationState.NEW, OrchestrationState.STOPPED}:
            return self.snapshot(now_epoch)
        if self.state in {OrchestrationState.BLOCKED, OrchestrationState.RECOVERING, OrchestrationState.KEEPALIVE_FAILED}:
            return self.snapshot(now_epoch)
        if self.websocket.socket_state is not SocketState.OPEN:
            self._controlled_reconnect(credential=credential, now_epoch=now_epoch)
            return self.snapshot(now_epoch)
        if self._next_keepalive_epoch is not None and now_epoch >= self._next_keepalive_epoch:
            self._keepalive_once(credential=credential, now_epoch=now_epoch)
        return self.snapshot(now_epoch)

    def on_socket_disconnect(self, *, now_epoch: float, cause: RecoveryCause = RecoveryCause.DISCONNECT) -> RuntimeCycleSnapshot:
        self.websocket.on_disconnect(now_epoch=now_epoch)
        self.state = OrchestrationState.RECONNECTING
        self.last_action = "SOCKET_DISCONNECTED"
        self.reason = cause.value
        return self.snapshot(now_epoch)

    def on_listen_key_expiry(self, *, now_epoch: float) -> RuntimeCycleSnapshot:
        self.coordinator.listen_key_expired(now_epoch=now_epoch)
        if self.websocket.socket_state is SocketState.OPEN:
            self.websocket.on_disconnect(now_epoch=now_epoch)
        self.state = OrchestrationState.RECONNECTING
        self.last_action = "LISTEN_KEY_EXPIRED"
        self.reason = "LISTEN_KEY_EXPIRED"
        self._next_keepalive_epoch = None
        return self.snapshot(now_epoch)

    def recover(self, *, credential: RuntimeCredential, now_epoch: float) -> RuntimeCycleSnapshot:
        if self.state not in {OrchestrationState.RECONNECTING, OrchestrationState.KEEPALIVE_FAILED, OrchestrationState.RECOVERING}:
            raise ValueError("RECOVERY_NOT_SCHEDULED")
        if self.state in {OrchestrationState.RECONNECTING, OrchestrationState.KEEPALIVE_FAILED}:
            self._controlled_reconnect(credential=credential, now_epoch=now_epoch)
            if self.state is not OrchestrationState.RECOVERING:
                return self.snapshot(now_epoch)
        result = self.websocket.run_recovery(self.recovery, now_epoch=now_epoch)
        self.state = OrchestrationState.ACTIVE if result.trading_allowed else OrchestrationState.BLOCKED
        self.last_action = "RECOVERY_VERIFIED" if result.trading_allowed else "RECOVERY_FAILED"
        self.reason = result.reason
        if result.trading_allowed:
            self._next_keepalive_epoch = now_epoch + self.control.config.keepalive_interval_s
        return self.snapshot(now_epoch)

    def stop(self, *, credential: RuntimeCredential, now_epoch: float) -> RuntimeCycleSnapshot:
        if self.state is OrchestrationState.STOPPED:
            return self.snapshot(now_epoch)
        self.state = OrchestrationState.STOPPING
        key = self.coordinator.listen_key
        if key:
            try:
                self.control.stop(key, credential)
            except (ControlTransportError, ControlResponseError):
                self.failure_count += 1
                # Quarantine instead of assuming STOP succeeded.
                self.websocket.on_disconnect(now_epoch=now_epoch) if self.websocket.socket_state is SocketState.OPEN else None
                self.state = OrchestrationState.BLOCKED
                self.last_action = "STOP_UNCERTAIN"
                self.reason = "CONTROL_STOP_UNCERTAIN"
                return self.snapshot(now_epoch)
        self.websocket.close(now_epoch=now_epoch)
        self.state = OrchestrationState.STOPPED
        self.last_action = "STOP_OK"
        self.reason = "STOPPED"
        self._next_keepalive_epoch = None
        return self.snapshot(now_epoch)

    def _keepalive_once(self, *, credential: RuntimeCredential, now_epoch: float) -> None:
        try:
            listen_key = self.coordinator.listen_key
            if not listen_key:
                raise PermissionError("LISTEN_KEY_REQUIRED")
            key = self.control.ping(listen_key, credential)
            self.coordinator.keepalive_succeeded(listen_key=key, now_epoch=now_epoch)
            self.websocket.last_ping_epoch = now_epoch
            self._next_keepalive_epoch = now_epoch + self.control.config.keepalive_interval_s
            self.state = OrchestrationState.ACTIVE
            self.last_action = "KEEPALIVE_OK"
            self.reason = "KEEPALIVE_OK"
        except (ControlTransportError, ControlResponseError, PermissionError):
            self.failure_count += 1
            self.state = OrchestrationState.KEEPALIVE_FAILED
            self.last_action = "KEEPALIVE_FAILED"
            self.reason = "KEEPALIVE_FAILED"
            self.coordinator.listen_key_expired(now_epoch=now_epoch)
            if self.websocket.socket_state is SocketState.OPEN:
                self.websocket.on_disconnect(now_epoch=now_epoch)

    def _controlled_reconnect(self, *, credential: RuntimeCredential, now_epoch: float) -> None:
        self.state = OrchestrationState.RECONNECTING
        try:
            key = self.control.start(credential)
        except (ControlTransportError, ControlResponseError, PermissionError) as exc:
            self.failure_count += 1
            self.state = OrchestrationState.BLOCKED
            self.last_action = "CONTROL_START_FAILED"
            self.reason = type(exc).__name__
            return
        try:
            if self.websocket.socket_state is SocketState.OPEN:
                self.websocket.on_disconnect(now_epoch=now_epoch)
            self.websocket.reconnect(listen_key=key, now_epoch=now_epoch)
        except Exception as exc:
            self.failure_count += 1
            self.state = OrchestrationState.BLOCKED
            self.last_action = "RECONNECT_FAILED"
            self.reason = type(exc).__name__
            return
        self.state = OrchestrationState.RECOVERING
        self.last_action = "RECONNECT_OK"
        self.reason = "REQUIRES_RECONCILIATION"

    def snapshot(self, now_epoch: float) -> RuntimeCycleSnapshot:
        session = self.coordinator.snapshot(now_epoch)
        ws = self.websocket.snapshot(now_epoch)
        keepalive_due = self._next_keepalive_epoch is not None and now_epoch >= self._next_keepalive_epoch
        return RuntimeCycleSnapshot(
            state=self.state,
            session_state=session.state,
            socket_state=ws.socket_state,
            listen_key_present=bool(self.coordinator.listen_key),
            trading_allowed=(self.state is OrchestrationState.ACTIVE and ws.trading_allowed and session.trading_allowed),
            keepalive_due=keepalive_due,
            recovery_required=session.recovery_required,
            last_action=self.last_action,
            failure_count=self.failure_count,
            reason=self.reason,
        )

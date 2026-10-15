"""V3.82 authenticated Binance USDⓈ-M Testnet session boundary.

Separates:
- USER_STREAM control-plane (userDataStream.start/ping/stop);
- private user-data WebSocket transport;
- deterministic v3.80 user-data projection/reconciliation;
- runtime credential handling and fail-closed session state.

No secret is persisted by the session object. Live network I/O is opt-in through an
injected transport/configuration and remains forbidden for non-Testnet endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
import time
import uuid
from typing import Any, Callable, Mapping, Protocol

from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.v39.binance_user_data_control import (
    BinanceUserDataControl,
    BinanceUserDataControlConfig,
    BinanceUserDataControlTransport,
    ControlResponseError,
    ControlTransportError,
    RuntimeCredential,
)
from trading_platform.v380 import BinancePrivateWebSocketConfig, BinanceUserDataProjection, UserDataApplyResult, UserDataHealth


class AuthSessionState(str, Enum):
    NEW = "NEW"
    STARTING = "STARTING"
    STREAMING = "STREAMING"
    DEGRADED = "DEGRADED"
    EXPIRED = "EXPIRED"
    STOPPED = "STOPPED"


class WebSocketTransport(Protocol):
    def connect(self, url: str) -> None: ...
    def send(self, payload: str) -> None: ...
    def recv(self, timeout_s: float) -> str | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class AuthenticatedTestnetConfigV382:
    environment: str = "TESTNET"
    control_url: str = ""
    private_ws_config: BinancePrivateWebSocketConfig = BinancePrivateWebSocketConfig(environment="TESTNET")
    recv_timeout_s: float = 5.0
    keepalive_interval_s: float = 3300.0

    @classmethod
    def from_env(cls) -> "AuthenticatedTestnetConfigV382":
        return cls(
            environment=os.getenv("BINANCE_TESTNET_ENV", "TESTNET"),
            control_url=os.getenv("BINANCE_TESTNET_WS_API_URL", ""),
            private_ws_config=BinancePrivateWebSocketConfig(environment=os.getenv("BINANCE_TESTNET_ENV", "TESTNET")),
            recv_timeout_s=float(os.getenv("BINANCE_TESTNET_WS_RECV_TIMEOUT_S", "5")),
            keepalive_interval_s=float(os.getenv("BINANCE_TESTNET_USER_STREAM_KEEPALIVE_S", "3300")),
        )

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise ValueError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if self.recv_timeout_s <= 0:
            raise ValueError("INVALID_RECV_TIMEOUT")
        if not 0 < self.keepalive_interval_s < 3600:
            raise ValueError("INVALID_KEEPALIVE_INTERVAL")
        if self.control_url:
            TESTNET_POLICY.assert_allowed(self.control_url)
            if not self.control_url.endswith("/ws-fapi/v1"):
                raise ValueError("UNEXPECTED_WS_API_PATH")


@dataclass(frozen=True)
class AuthSessionSnapshotV382:
    state: AuthSessionState
    listen_key_present: bool
    control_healthy: bool
    stream_health: UserDataHealth
    trading_allowed: bool
    next_keepalive_epoch: float | None
    reason: str


class BinanceWebSocketApiControlTransportV382(BinanceUserDataControlTransport):
    """Real WebSocket-API transport. One request gets one short-lived socket."""

    def __init__(self, transport_factory: Callable[[], WebSocketTransport], *, timeout_s: float = 10.0) -> None:
        if timeout_s <= 0:
            raise ValueError("INVALID_CONTROL_TIMEOUT")
        self.transport_factory = transport_factory
        self.timeout_s = timeout_s

    def request(self, *, url: str, payload: Mapping[str, Any], api_key: str) -> Mapping[str, Any]:
        TESTNET_POLICY.assert_allowed(url)
        transport = self.transport_factory()
        transport.connect(url)
        try:
            transport.send(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                raw = transport.recv(max(0.1, min(1.0, deadline - time.monotonic())))
                if raw is None:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ControlTransportError("CONTROL_MALFORMED_JSON") from exc
                if isinstance(obj, Mapping) and obj.get("id") == payload.get("id"):
                    return obj
            raise ControlTransportError("CONTROL_RESPONSE_TIMEOUT")
        finally:
            transport.close()


class WebSocketClientTransportV382:
    """Adapter around websocket-client; import is deferred until live use."""

    def __init__(self) -> None:
        self._ws: Any = None

    def connect(self, url: str) -> None:
        from websocket import create_connection
        TESTNET_POLICY.assert_allowed(url)
        self._ws = create_connection(url, timeout=10)

    def send(self, payload: str) -> None:
        if self._ws is None:
            raise RuntimeError("WEBSOCKET_NOT_CONNECTED")
        self._ws.send(payload)

    def recv(self, timeout_s: float) -> str | None:
        if self._ws is None:
            raise RuntimeError("WEBSOCKET_NOT_CONNECTED")
        self._ws.settimeout(timeout_s)
        try:
            return self._ws.recv()
        except TimeoutError:
            return None

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None


class BinanceAuthenticatedTestnetSessionV382:
    """Controlled authenticated Testnet user-data session.

    The session does not submit orders. It only establishes the authenticated user
    stream, projects private events and exposes the reconciliation gate.
    """

    def __init__(
        self,
        *,
        config: AuthenticatedTestnetConfigV382,
        control: BinanceUserDataControl,
        stream_transport: WebSocketTransport,
        clock: Callable[[], float] = time.time,
    ) -> None:
        config.validate()
        self.config = config
        self.control = control
        self.stream_transport = stream_transport
        self.clock = clock
        self.projection = BinanceUserDataProjection()
        self.state = AuthSessionState.NEW
        self.control_healthy = False
        self.listen_key: str | None = None
        self.next_keepalive_epoch: float | None = None
        self.reason = "INITIAL"
        self._credential: RuntimeCredential | None = None

    def _stream_url(self, listen_key: str) -> str:
        return self.config.private_ws_config.url(listen_key=listen_key, events=["ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE"])

    def start(self, *, api_key: str, now_epoch: float | None = None) -> AuthSessionSnapshotV382:
        now = self.clock() if now_epoch is None else now_epoch
        if not api_key:
            raise PermissionError("RUNTIME_API_KEY_REQUIRED")
        if not self.config.control_url:
            self.state = AuthSessionState.DEGRADED
            self.reason = "CONTROL_URL_NOT_CONFIGURED"
            return self.snapshot(now)
        self.state = AuthSessionState.STARTING
        self._credential = RuntimeCredential(api_key=api_key)
        try:
            key = self.control.start(self._credential)
            self.stream_transport.connect(self._stream_url(key))
        except Exception:
            self.state = AuthSessionState.DEGRADED
            self.control_healthy = False
            self.reason = "START_FAILED"
            self._credential = None
            return self.snapshot(now)
        self.projection.start()
        self.listen_key = key
        self.control_healthy = True
        self.state = AuthSessionState.STREAMING
        self.next_keepalive_epoch = now + self.config.keepalive_interval_s
        self.reason = "STREAMING"
        return self.snapshot(now)

    def keepalive(self, *, now_epoch: float | None = None) -> AuthSessionSnapshotV382:
        now = self.clock() if now_epoch is None else now_epoch
        if self.state is not AuthSessionState.STREAMING or not self.listen_key or not self._credential:
            raise PermissionError("AUTH_SESSION_NOT_STREAMING")
        try:
            refreshed = self.control.ping(self.listen_key, self._credential)
            if refreshed != self.listen_key:
                self.stream_transport.close()
                self.stream_transport.connect(self._stream_url(refreshed))
                self.listen_key = refreshed
        except (ControlTransportError, ControlResponseError, OSError, RuntimeError):
            self.control_healthy = False
            self.state = AuthSessionState.DEGRADED
            self.reason = "KEEPALIVE_FAILED"
            return self.snapshot(now)
        self.control_healthy = True
        self.next_keepalive_epoch = now + self.config.keepalive_interval_s
        self.reason = "KEEPALIVE_OK"
        return self.snapshot(now)

    def receive_once(self, *, now_epoch: float | None = None) -> UserDataApplyResult | None:
        now = self.clock() if now_epoch is None else now_epoch
        if self.state is not AuthSessionState.STREAMING:
            raise PermissionError("AUTH_SESSION_NOT_STREAMING")
        raw = self.stream_transport.recv(self.config.recv_timeout_s)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.state = AuthSessionState.DEGRADED
            self.reason = "MALFORMED_WS_JSON"
            raise RuntimeError("MALFORMED_WS_JSON")
        if not isinstance(payload, Mapping):
            self.state = AuthSessionState.DEGRADED
            self.reason = "MALFORMED_WS_PAYLOAD"
            raise RuntimeError("MALFORMED_WS_PAYLOAD")
        result = self.projection.apply(payload, now_epoch=now)
        if str(payload.get("e", "")) == "listenKeyExpired":
            self.control_healthy = False
            self.state = AuthSessionState.EXPIRED
            self.reason = "LISTEN_KEY_EXPIRED"
        elif not result.accepted:
            self.state = AuthSessionState.DEGRADED
            self.reason = result.reason.value
        return result

    def reconcile(self, rest_account: Mapping[str, Any], *, now_epoch: float | None = None):
        now = self.clock() if now_epoch is None else now_epoch
        return self.projection.reconcile(rest_account, now_epoch=now)

    def stop(self, *, now_epoch: float | None = None) -> AuthSessionSnapshotV382:
        now = self.clock() if now_epoch is None else now_epoch
        stop_error = False
        try:
            if self.listen_key and self._credential and self.config.control_url:
                try:
                    self.control.stop(self.listen_key, self._credential)
                except (ControlTransportError, ControlResponseError, OSError, RuntimeError):
                    stop_error = True
            self.stream_transport.close()
        finally:
            self.state = AuthSessionState.DEGRADED if stop_error else AuthSessionState.STOPPED
            self.control_healthy = False
            self.next_keepalive_epoch = None
            self.reason = "CONTROL_STOP_UNCERTAIN" if stop_error else "STOPPED"
            self.listen_key = None
            self._credential = None
        return self.snapshot(now)

    def snapshot(self, now_epoch: float | None = None) -> AuthSessionSnapshotV382:
        now = self.clock() if now_epoch is None else now_epoch
        stream_health = self.projection.snapshot(now_epoch=now).health
        return AuthSessionSnapshotV382(
            state=self.state,
            listen_key_present=bool(self.listen_key),
            control_healthy=self.control_healthy,
            stream_health=stream_health,
            trading_allowed=self.state is AuthSessionState.STREAMING and self.control_healthy and self.projection.snapshot(now_epoch=now).trading_allowed,
            next_keepalive_epoch=self.next_keepalive_epoch,
            reason=self.reason,
        )

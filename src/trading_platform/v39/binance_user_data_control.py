from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import uuid
from typing import Any, Callable, Mapping, Protocol

from trading_platform.v37.user_stream_runtime import (
    SessionState,
    UserStreamSessionCoordinator,
)
from trading_platform.v38.websocket_runtime import BinanceUserStreamRuntime


class ControlMethod(str, Enum):
    START = "userDataStream.start"
    PING = "userDataStream.ping"
    STOP = "userDataStream.stop"


class ControlTransportError(RuntimeError):
    """Transport or malformed-response failure; outcome is not assumed successful."""


class ControlResponseError(RuntimeError):
    """Binance control-plane response is explicit but unsuccessful."""


class BinanceUserDataControlTransport(Protocol):
    def request(self, *, url: str, payload: Mapping[str, Any], api_key: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RuntimeCredential:
    api_key: str

    def value(self) -> str:
        if not self.api_key:
            raise PermissionError("RUNTIME_API_KEY_REQUIRED")
        return self.api_key


@dataclass(frozen=True)
class BinanceUserDataControlConfig:
    url: str = "wss://ws-fapi.binance.com/ws-fapi/v1"
    keepalive_interval_s: float = 3300.0

    def validate(self) -> None:
        if not self.url.startswith("wss://"):
            raise ValueError("TLS_CONTROL_WEBSOCKET_REQUIRED")
        if self.keepalive_interval_s <= 0:
            raise ValueError("KEEPALIVE_INTERVAL_REQUIRED")
        if self.keepalive_interval_s >= 3600.0:
            raise ValueError("KEEPALIVE_INTERVAL_MUST_PRECEDE_EXPIRY")


@dataclass(frozen=True)
class ControlPlaneSnapshot:
    listen_key: str | None
    listen_key_present: bool
    state: SessionState
    last_control_epoch: float | None
    last_method: str | None
    next_keepalive_epoch: float | None
    control_healthy: bool
    reason: str


class BinanceUserDataControl:
    """Network-injected Binance USDⓈ-M user-data stream control plane.

    Credentials are accepted per operation and never persisted. A successful START/PING
    response must contain an explicit listenKey. Failures never manufacture or retain a
    new key; the session coordinator is moved to a recovery/expired state by the manager.
    """

    def __init__(
        self,
        *,
        transport: BinanceUserDataControlTransport,
        config: BinanceUserDataControlConfig = BinanceUserDataControlConfig(),
        request_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        config.validate()
        self.transport = transport
        self.config = config
        self.request_id = request_id

    def _request(self, method: ControlMethod, credential: RuntimeCredential, *, listen_key: str | None = None) -> str | None:
        api_key = credential.value()
        params: dict[str, Any] = {"apiKey": api_key}
        # Binance WS API control methods authenticate with apiKey; listenKey is retained locally
        # for websocket correlation and is not sent as a control-plane parameter here.
        payload = {"id": self.request_id(), "method": method.value, "params": params}
        try:
            response = self.transport.request(url=self.config.url, payload=payload, api_key=api_key)
        except Exception as exc:
            raise ControlTransportError(f"{method.value}:TRANSPORT_FAILURE") from exc
        if not isinstance(response, Mapping):
            raise ControlTransportError(f"{method.value}:MALFORMED_RESPONSE")
        status = response.get("status")
        if status != 200:
            raise ControlResponseError(f"{method.value}:STATUS_{status}")
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ControlResponseError(f"{method.value}:RESULT_MISSING")
        if method in {ControlMethod.START, ControlMethod.PING}:
            key = result.get("listenKey")
            if not isinstance(key, str) or not key:
                raise ControlResponseError(f"{method.value}:LISTEN_KEY_MISSING")
            return key
        return None

    def start(self, credential: RuntimeCredential) -> str:
        result = self._request(ControlMethod.START, credential)
        assert result is not None
        return result

    def ping(self, listen_key: str, credential: RuntimeCredential) -> str:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        result = self._request(ControlMethod.PING, credential, listen_key=listen_key)
        assert result is not None
        return result

    def stop(self, listen_key: str, credential: RuntimeCredential) -> None:
        if not listen_key:
            raise ValueError("LISTEN_KEY_REQUIRED")
        self._request(ControlMethod.STOP, credential, listen_key=listen_key)


class BinanceUserDataSessionManager:
    """Coordinates the control plane with V3.8 socket/session state.

    The manager treats control-plane failures as safety failures. A ping timeout/error or
    listenKey-expired event never keeps trading enabled; recovery must be re-established.
    """

    def __init__(
        self,
        *,
        coordinator: UserStreamSessionCoordinator,
        control: BinanceUserDataControl,
        websocket: BinanceUserStreamRuntime | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.control = control
        self.websocket = websocket
        self.last_control_epoch: float | None = None
        self.last_method: str | None = None
        self.control_healthy = False
        self.reason = "INITIAL"
        self._next_keepalive_epoch: float | None = None

    def start(self, *, credential: RuntimeCredential, now_epoch: float) -> ControlPlaneSnapshot:
        key = self.control.start(credential)
        if self.websocket is not None:
            self.websocket.start(listen_key=key, now_epoch=now_epoch)
        else:
            self.coordinator.start(listen_key=key, now_epoch=now_epoch)
        self.last_control_epoch = now_epoch
        self.last_method = ControlMethod.START.value
        self.control_healthy = True
        self.reason = "CONTROL_START_OK"
        self._next_keepalive_epoch = now_epoch + self.control.config.keepalive_interval_s
        return self.snapshot()

    def keepalive_due(self, now_epoch: float) -> bool:
        return self._next_keepalive_epoch is not None and now_epoch >= self._next_keepalive_epoch

    def keepalive(self, *, credential: RuntimeCredential, now_epoch: float) -> ControlPlaneSnapshot:
        if not self.coordinator.listen_key:
            raise PermissionError("LISTEN_KEY_REQUIRED")
        try:
            key = self.control.ping(self.coordinator.listen_key, credential)
        except (ControlTransportError, ControlResponseError):
            self.control_healthy = False
            self.reason = "CONTROL_KEEPALIVE_FAILED"
            self.coordinator.listen_key_expired(now_epoch=now_epoch)
            return self.snapshot()
        # A successful ping can return the current active listenKey. Preserve the newest key.
        self.coordinator.keepalive_succeeded(listen_key=key, now_epoch=now_epoch)
        self.last_control_epoch = now_epoch
        self.last_method = ControlMethod.PING.value
        self.control_healthy = True
        self.reason = "CONTROL_KEEPALIVE_OK"
        self._next_keepalive_epoch = now_epoch + self.control.config.keepalive_interval_s
        return self.snapshot()

    def handle_expiry(self, *, now_epoch: float) -> ControlPlaneSnapshot:
        self.coordinator.listen_key_expired(now_epoch=now_epoch)
        self.control_healthy = False
        self.reason = "LISTEN_KEY_EXPIRED"
        self._next_keepalive_epoch = None
        return self.snapshot()

    def stop(self, *, credential: RuntimeCredential, now_epoch: float) -> ControlPlaneSnapshot:
        key = self.coordinator.listen_key
        if key:
            try:
                self.control.stop(key, credential)
            except (ControlTransportError, ControlResponseError):
                self.control_healthy = False
                self.reason = "CONTROL_STOP_UNCERTAIN"
                self.coordinator.listen_key_expired(now_epoch=now_epoch)
                return self.snapshot()
        if self.websocket is not None:
            self.websocket.close(now_epoch=now_epoch)
        else:
            self.coordinator.close(now_epoch=now_epoch)
        self.control_healthy = False
        self.last_method = ControlMethod.STOP.value
        self.reason = "CONTROL_STOP_OK"
        self._next_keepalive_epoch = None
        return self.snapshot()

    def snapshot(self) -> ControlPlaneSnapshot:
        key = self.coordinator.listen_key
        state = self.coordinator.state
        return ControlPlaneSnapshot(
            listen_key=key,
            listen_key_present=bool(key),
            state=state,
            last_control_epoch=self.last_control_epoch,
            last_method=self.last_method,
            next_keepalive_epoch=self._next_keepalive_epoch,
            control_healthy=self.control_healthy,
            reason=self.reason,
        )

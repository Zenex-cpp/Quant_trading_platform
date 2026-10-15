from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol
from decimal import Decimal

from trading_platform.execution.models import OrderRequest
from trading_platform.execution.lifecycle import OrderExecutionState
from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.testnet.client import BinanceTestnetClient, TestnetClientConfig

class ExchangeOutcome(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"

class ExchangeUncertain(RuntimeError):
    """Transport-level uncertainty: the exchange may have accepted the request."""

class RuntimeCredentials(Protocol):
    def values(self) -> tuple[str, bytes]: ...

@dataclass(frozen=True)
class RuntimeCredentialValues:
    api_key: str
    api_secret: bytes
    def values(self) -> tuple[str, bytes]:
        if not self.api_key or not self.api_secret:
            raise ValueError("RUNTIME_CREDENTIALS_REQUIRED")
        return self.api_key, self.api_secret

@dataclass(frozen=True)
class BinanceTestnetExecutionConfig:
    base_url: str = "https://testnet.binancefuture.com"
    environment: str = "TESTNET"
    recv_window_ms: int = 5000
    timeout_s: float = 10.0

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise ValueError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not self.base_url.startswith("https://"):
            raise ValueError("TLS_REQUIRED")
        TESTNET_POLICY.assert_allowed(self.base_url)
        if self.recv_window_ms <= 0:
            raise ValueError("INVALID_RECV_WINDOW")

@dataclass(frozen=True)
class SubmitObservation:
    outcome: ExchangeOutcome
    client_order_id: str
    exchange_order_id: str | None
    raw: Mapping[str, Any] | None = None
    reason: str | None = None

class BinanceTestnetExecutionGateway:
    """Signed Binance USDⓈ-M Testnet gateway.

    Runtime credentials are passed into each mutating/query operation and are never
    retained by this gateway. No method defaults to mainnet or performs network I/O
    unless explicitly called by the operator.
    """
    __test__ = False
    ORDER_PATH = "/fapi/v1/order"

    def __init__(self, config: BinanceTestnetExecutionConfig | None = None):
        self.config = config or BinanceTestnetExecutionConfig()
        self.config.validate()

    def _client(self, creds: RuntimeCredentialValues) -> BinanceTestnetClient:
        key, _ = creds.values()
        cfg = TestnetClientConfig(
            base_url=self.config.base_url,
            api_key_ref="runtime",
            secret_ref="runtime",
            environment=self.config.environment,
            recv_window_ms=self.config.recv_window_ms,
        )
        from trading_platform.testnet.client import BinanceTestnetClient as _Client
        return _Client(cfg, _Transport(self.config.timeout_s))

    @staticmethod
    def _params(order: OrderRequest) -> dict[str, str]:
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            "quantity": str(order.quantity),
            "newClientOrderId": order.client_order_id,
        }

    def submit(self, order: OrderRequest, *, credentials: RuntimeCredentialValues) -> SubmitObservation:
        if not order.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        key, secret = credentials.values()
        client = self._client(credentials)
        try:
            raw = client.signed_request("POST", self.ORDER_PATH, params=self._params(order), api_key=key, secret=secret)
        except Exception as exc:  # transport uncertainty must not become a retry instruction
            raise ExchangeUncertain("SUBMIT_OUTCOME_UNKNOWN") from exc
        status = str(raw.get("status", "")).upper()
        ex_id = str(raw["orderId"]) if raw.get("orderId") is not None else None
        if status in {"NEW", "PARTIALLY_FILLED", "FILLED"}:
            outcome = ExchangeOutcome.ACKNOWLEDGED
        elif status in {"REJECTED", "EXPIRED"}:
            outcome = ExchangeOutcome.REJECTED
        else:
            outcome = ExchangeOutcome.UNKNOWN
        return SubmitObservation(outcome, order.client_order_id, ex_id, raw=raw)

    def query(self, *, symbol: str, client_order_id: str, credentials: RuntimeCredentialValues) -> SubmitObservation:
        if not symbol or not client_order_id:
            raise ValueError("QUERY_CORRELATION_REQUIRED")
        key, secret = credentials.values()
        client = self._client(credentials)
        try:
            raw = client.signed_request(
                "GET", self.ORDER_PATH,
                params={"symbol": symbol, "origClientOrderId": client_order_id},
                api_key=key, secret=secret,
            )
        except Exception as exc:
            raise ExchangeUncertain("QUERY_OUTCOME_UNKNOWN") from exc
        status = str(raw.get("status", "")).upper()
        ex_id = str(raw["orderId"]) if raw.get("orderId") is not None else None
        mapping = {
            "NEW": ExchangeOutcome.ACKNOWLEDGED,
            "PARTIALLY_FILLED": ExchangeOutcome.ACKNOWLEDGED,
            "FILLED": ExchangeOutcome.ACKNOWLEDGED,
            "CANCELED": ExchangeOutcome.CANCELLED,
            "CANCELLED": ExchangeOutcome.CANCELLED,
            "REJECTED": ExchangeOutcome.REJECTED,
            "EXPIRED": ExchangeOutcome.REJECTED,
        }
        return SubmitObservation(mapping.get(status, ExchangeOutcome.UNKNOWN), client_order_id, ex_id, raw=raw)

    def cancel(self, *, symbol: str, client_order_id: str, credentials: RuntimeCredentialValues) -> SubmitObservation:
        if not symbol or not client_order_id:
            raise ValueError("CANCEL_CORRELATION_REQUIRED")
        key, secret = credentials.values()
        client = self._client(credentials)
        try:
            raw = client.signed_request(
                "DELETE", self.ORDER_PATH,
                params={"symbol": symbol, "origClientOrderId": client_order_id},
                api_key=key, secret=secret,
            )
        except Exception as exc:
            raise ExchangeUncertain("CANCEL_OUTCOME_UNKNOWN") from exc
        status = str(raw.get("status", "")).upper()
        ex_id = str(raw["orderId"]) if raw.get("orderId") is not None else None
        if status in {"CANCELED", "CANCELLED"}:
            return SubmitObservation(ExchangeOutcome.CANCELLED, client_order_id, ex_id, raw=raw)
        if status in {"REJECTED", "EXPIRED"}:
            return SubmitObservation(ExchangeOutcome.REJECTED, client_order_id, ex_id, raw=raw)
        return SubmitObservation(ExchangeOutcome.UNKNOWN, client_order_id, ex_id, raw=raw)

    @staticmethod
    def lifecycle_target(observation: SubmitObservation) -> OrderExecutionState:
        return {
            ExchangeOutcome.ACKNOWLEDGED: OrderExecutionState.ACKNOWLEDGED,
            ExchangeOutcome.REJECTED: OrderExecutionState.REJECTED,
            ExchangeOutcome.CANCELLED: OrderExecutionState.CANCELLED,
            ExchangeOutcome.UNKNOWN: OrderExecutionState.UNKNOWN,
        }[observation.outcome]

class _Transport:
    def __init__(self, timeout_s: float):
        self.timeout_s = timeout_s
    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                params: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        import json
        from urllib.request import Request, urlopen
        from urllib.parse import urlencode
        body = urlencode(params or {}).encode()
        if method == "GET":
            final = url + (("?" + body.decode()) if body else "")
            req = Request(final, method="GET", headers=dict(headers or {}))
        elif method == "DELETE":
            final = url + (("?" + body.decode()) if body else "")
            req = Request(final, method="DELETE", headers=dict(headers or {}))
        else:
            req = Request(url, data=body, method=method, headers={**dict(headers or {}), "Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

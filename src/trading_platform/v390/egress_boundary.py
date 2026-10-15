"""V3.90 Testnet egress isolation boundary.

M25 requires research isolation from production trading endpoints. The same
principle must hold on the credentialed Testnet path: an allowed hostname is
not sufficient if ambient proxy settings or redirects can move the request to
another destination. V3.90 therefore binds each outbound Testnet request to an
exact HTTPS host, disables ambient proxies and rejects redirects.

No order is submitted by this module during construction or validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
import json
import os

from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.testnet.client import BinanceTestnetClient, TestnetClientConfig
from trading_platform.v380.order_adapter import BinanceV380TestnetExecutionGateway
from trading_platform.v35.binance_execution import RuntimeCredentialValues


class EgressDecisionV390(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class EgressBoundaryErrorV390(PermissionError):
    __test__ = False


_PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


@dataclass(frozen=True)
class EgressPolicyV390:
    environment: str = "TESTNET"
    rest_host: str = "testnet.binancefuture.com"
    ws_hosts: frozenset[str] = frozenset({"fstream.binancefuture.com"})
    tls_required: bool = True
    block_ambient_proxy: bool = True
    reject_redirects: bool = True

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise EgressBoundaryErrorV390("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not self.rest_host or self.rest_host.lower() != self.rest_host:
            raise EgressBoundaryErrorV390("REST_HOST_CANONICALIZATION_REQUIRED")
        if self.rest_host != "testnet.binancefuture.com":
            raise EgressBoundaryErrorV390("REST_HOST_NOT_EXACT_TESTNET")
        TESTNET_POLICY.assert_allowed("https://" + self.rest_host)
        for host in self.ws_hosts:
            if not host or host.lower() != host:
                raise EgressBoundaryErrorV390("WS_HOST_CANONICALIZATION_REQUIRED")
            TESTNET_POLICY.assert_allowed("wss://" + host)

    def decide(self, endpoint: str, *, websocket: bool = False) -> EgressDecisionV390:
        parsed = urlparse(endpoint)
        expected_scheme = "wss" if websocket else "https"
        if self.tls_required and parsed.scheme.lower() != expected_scheme:
            return EgressDecisionV390.DENY
        host = (parsed.hostname or "").lower().rstrip(".")
        if websocket:
            allowed = host in {h.rstrip(".") for h in self.ws_hosts}
        else:
            allowed = host == self.rest_host
        if not allowed:
            return EgressDecisionV390.DENY
        if parsed.username or parsed.password:
            return EgressDecisionV390.DENY
        if parsed.port not in (None, 443):
            return EgressDecisionV390.DENY
        return EgressDecisionV390.ALLOW

    def assert_allowed(self, endpoint: str, *, websocket: bool = False) -> None:
        if self.decide(endpoint, websocket=websocket) is not EgressDecisionV390.ALLOW:
            raise EgressBoundaryErrorV390("TESTNET_EGRESS_TARGET_DENIED")

    def assert_no_ambient_proxy(self, environ: Mapping[str, str] | None = None) -> None:
        if not self.block_ambient_proxy:
            return
        env = environ if environ is not None else os.environ
        configured = [name for name in _PROXY_VARS if env.get(name)]
        if configured:
            raise EgressBoundaryErrorV390("AMBIENT_PROXY_CONFIGURATION_BLOCKED")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise EgressBoundaryErrorV390("TESTNET_REDIRECT_BLOCKED")


class EgressTransportProtocol(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]: ...


class EgressTransportV390:
    """Stdlib transport with explicit Testnet egress controls."""

    __test__ = False

    def __init__(
        self,
        *,
        policy: EgressPolicyV390 | None = None,
        timeout_s: float = 10.0,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy or EgressPolicyV390()
        self.policy.validate()
        self.policy.assert_no_ambient_proxy(environ)
        if timeout_s <= 0:
            raise ValueError("INVALID_EGRESS_TIMEOUT")
        self.timeout_s = timeout_s
        # Empty ProxyHandler disables environment-provided proxies. The custom
        # redirect handler ensures a response cannot silently move to another host.
        self._opener = build_opener(
            ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.policy.assert_no_ambient_proxy()
        self.policy.assert_allowed(url)
        from urllib.parse import urlencode
        encoded = urlencode(dict(params or {}))
        target = url + (("?" + encoded) if encoded else "")
        self.policy.assert_allowed(target)
        payload = encoded.encode("utf-8") if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else None
        request_headers = dict(headers or {})
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = Request(target, data=payload, method=method.upper(), headers=request_headers)
        with self._opener.open(req, timeout=self.timeout_s) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {}
            parsed = json.loads(body)
            if not isinstance(parsed, Mapping):
                raise ValueError("NON_OBJECT_JSON")
            return parsed


class BinanceV390TestnetExecutionGateway(BinanceV380TestnetExecutionGateway):
    """V3.80 order adapter plus V3.90 transport-bound Testnet egress."""

    __test__ = False

    def __init__(self, config=None, *, egress_policy: EgressPolicyV390 | None = None, transport=None):
        super().__init__(config=config)
        self.egress_policy = egress_policy or EgressPolicyV390(rest_host=(urlparse(self.config.base_url).hostname or "").lower())
        self.egress_policy.validate()
        self.egress_policy.assert_allowed(self.config.base_url)
        self._egress_transport = transport or EgressTransportV390(policy=self.egress_policy, timeout_s=self.config.timeout_s)

    def _client(self, creds: RuntimeCredentialValues) -> BinanceTestnetClient:
        key, _ = creds.values()
        cfg = TestnetClientConfig(
            base_url=self.config.base_url,
            api_key_ref="runtime",
            secret_ref="runtime",
            environment=self.config.environment,
            recv_window_ms=self.config.recv_window_ms,
        )
        return BinanceTestnetClient(cfg, self._egress_transport)


class TestnetEgressAuthorityV390:
    """Pure authority facade for callers that need to gate a Testnet session."""

    __test__ = False

    def __init__(self, policy: EgressPolicyV390 | None = None, *, environ: Mapping[str, str] | None = None) -> None:
        self.policy = policy or EgressPolicyV390()
        self.policy.validate()
        self.environ = environ

    def authorize_rest(self, endpoint: str) -> None:
        self.policy.assert_no_ambient_proxy(self.environ)
        self.policy.assert_allowed(endpoint)

    def authorize_websocket(self, endpoint: str) -> None:
        self.policy.assert_no_ambient_proxy(self.environ)
        self.policy.assert_allowed(endpoint, websocket=True)

    def authorization_payload(self, *, endpoint: str) -> dict[str, str]:
        self.authorize_rest(endpoint)
        return {
            "environment": self.policy.environment,
            "endpoint_host": self.policy.rest_host,
            "endpoint_scheme": "https",
            "ambient_proxy": "BLOCKED",
            "redirects": "BLOCKED",
        }

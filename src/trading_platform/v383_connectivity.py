"""V3.83 controlled Testnet connectivity preflight.

This module verifies only network/connectivity prerequisites. It never submits orders
and never accepts production endpoints. Runtime network I/O is injectable for tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import socket
import time
from typing import Callable, Mapping, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from trading_platform.ops.network_policy import TESTNET_POLICY


class PreflightStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TestnetConnectivityConfigV383:
    __test__ = False
    environment: str = "TESTNET"
    rest_base_url: str = "https://testnet.binancefuture.com"
    ws_api_url: str = ""
    ws_private_url: str = ""
    timeout_s: float = 5.0
    max_clock_skew_ms: int = 5000

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise PermissionError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if self.timeout_s <= 0:
            raise ValueError("INVALID_PREFLIGHT_TIMEOUT")
        if self.max_clock_skew_ms <= 0:
            raise ValueError("INVALID_CLOCK_SKEW_LIMIT")
        for url in (self.rest_base_url, self.ws_api_url, self.ws_private_url):
            if not url:
                continue
            TESTNET_POLICY.assert_allowed(url)


class HttpTransport(Protocol):
    def get_json(self, url: str, timeout_s: float) -> Mapping[str, object]: ...


class Resolver(Protocol):
    def resolve(self, hostname: str) -> list[tuple]: ...


class DefaultHttpTransport:
    def get_json(self, url: str, timeout_s: float) -> Mapping[str, object]:
        req = Request(url, headers={"User-Agent": "trading-platform-v383-preflight/1"}, method="GET")
        with urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("NON_OBJECT_JSON")
        return payload


class DefaultResolver:
    def resolve(self, hostname: str) -> list[tuple]:
        return socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)


@dataclass(frozen=True)
class ConnectivityEvidenceV383:
    status: PreflightStatus
    rest_endpoint: str
    ws_api_endpoint: str
    ws_private_endpoint: str
    rest_dns: str
    rest_server_time_ms: int | None
    client_time_ms: int
    clock_skew_ms: int | None
    reason: str


class TestnetConnectivityPreflightV383:
    __test__ = False
    def __init__(
        self,
        *,
        config: TestnetConnectivityConfigV383,
        http: HttpTransport | None = None,
        resolver: Resolver | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.http = http or DefaultHttpTransport()
        self.resolver = resolver or DefaultResolver()
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def _check_host(self) -> tuple[str, str]:
        host = urlparse(self.config.rest_base_url).hostname
        if not host:
            return "INVALID", "REST_HOST_MISSING"
        try:
            records = self.resolver.resolve(host)
        except OSError as exc:
            return "UNRESOLVED", f"DNS_RESOLUTION_FAILED:{type(exc).__name__}"
        return ("RESOLVED" if records else "UNRESOLVED", "DNS_OK" if records else "DNS_EMPTY")

    def run(self) -> ConnectivityEvidenceV383:
        now = self.clock_ms()
        dns_status, dns_reason = self._check_host()
        if dns_status != "RESOLVED":
            return ConnectivityEvidenceV383(
                status=PreflightStatus.NOT_VERIFIED,
                rest_endpoint=self.config.rest_base_url,
                ws_api_endpoint=self.config.ws_api_url,
                ws_private_endpoint=self.config.ws_private_url,
                rest_dns=dns_status,
                rest_server_time_ms=None,
                client_time_ms=now,
                clock_skew_ms=None,
                reason=dns_reason,
            )
        try:
            payload = self.http.get_json(f"{self.config.rest_base_url.rstrip('/')}/fapi/v1/time", self.config.timeout_s)
            server_ms = int(payload["serverTime"])
        except (OSError, TimeoutError, KeyError, TypeError, ValueError) as exc:
            return ConnectivityEvidenceV383(
                status=PreflightStatus.FAILED,
                rest_endpoint=self.config.rest_base_url,
                ws_api_endpoint=self.config.ws_api_url,
                ws_private_endpoint=self.config.ws_private_url,
                rest_dns=dns_status,
                rest_server_time_ms=None,
                client_time_ms=now,
                clock_skew_ms=None,
                reason=f"REST_TIME_PROBE_FAILED:{type(exc).__name__}",
            )
        skew = now - server_ms
        if abs(skew) > self.config.max_clock_skew_ms:
            return ConnectivityEvidenceV383(
                status=PreflightStatus.BLOCKED,
                rest_endpoint=self.config.rest_base_url,
                ws_api_endpoint=self.config.ws_api_url,
                ws_private_endpoint=self.config.ws_private_url,
                rest_dns=dns_status,
                rest_server_time_ms=server_ms,
                client_time_ms=now,
                clock_skew_ms=skew,
                reason="CLOCK_SKEW_EXCEEDS_LIMIT",
            )
        return ConnectivityEvidenceV383(
            status=PreflightStatus.VERIFIED,
            rest_endpoint=self.config.rest_base_url,
            ws_api_endpoint=self.config.ws_api_url,
            ws_private_endpoint=self.config.ws_private_url,
            rest_dns=dns_status,
            rest_server_time_ms=server_ms,
            client_time_ms=now,
            clock_skew_ms=skew,
            reason="REST_CONNECTIVITY_AND_CLOCK_VERIFIED",
        )

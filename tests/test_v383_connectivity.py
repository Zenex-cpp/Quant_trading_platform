from __future__ import annotations

import pytest
from urllib.parse import urlparse

from trading_platform.v383 import (
    PreflightStatus,
    TestnetConnectivityConfigV383,
    TestnetConnectivityPreflightV383,
)


class Resolver:
    def __init__(self, ok=True): self.ok = ok
    def resolve(self, hostname):
        if not self.ok: raise OSError("dns")
        return [(2, 1, 6, "", ("127.0.0.1", 443))]


class Http:
    def __init__(self, payload=None): self.payload = payload or {"serverTime": 1_000_000}
    def get_json(self, url, timeout_s):
        assert url == "https://testnet.binancefuture.com/fapi/v1/time"
        assert timeout_s == 2.0
        return self.payload


def cfg():
    return TestnetConnectivityConfigV383(timeout_s=2.0, ws_api_url="wss://testnet.binancefuture.com/private", ws_private_url="wss://testnet.binancefuture.com/private")


def test_verified_rest_and_clock():
    p = TestnetConnectivityPreflightV383(config=cfg(), resolver=Resolver(), http=Http(), clock_ms=lambda: 1_001_000)
    e = p.run()
    assert e.status is PreflightStatus.VERIFIED
    assert e.clock_skew_ms == 1000


def test_dns_failure_is_not_verified():
    p = TestnetConnectivityPreflightV383(config=cfg(), resolver=Resolver(False), http=Http(), clock_ms=lambda: 1_001_000)
    e = p.run()
    assert e.status is PreflightStatus.NOT_VERIFIED
    assert e.rest_dns == "UNRESOLVED"


def test_clock_skew_blocks():
    p = TestnetConnectivityPreflightV383(config=cfg(), resolver=Resolver(), http=Http(), clock_ms=lambda: 1_010_001)
    e = p.run()
    assert e.status is PreflightStatus.BLOCKED
    assert e.reason == "CLOCK_SKEW_EXCEEDS_LIMIT"


def test_production_rest_is_rejected():
    with pytest.raises(PermissionError):
        TestnetConnectivityConfigV383(rest_base_url="https://fapi.binance.com").validate()


def test_invalid_scheme_is_rejected():
    with pytest.raises(PermissionError):
        TestnetConnectivityConfigV383(rest_base_url="http://testnet.binancefuture.com").validate()


def test_ws_endpoint_is_optional_but_network_policy_checked():
    c = TestnetConnectivityConfigV383(ws_api_url="wss://testnet.binancefuture.com/ws-fapi/v1")
    c.validate()

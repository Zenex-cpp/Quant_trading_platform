from __future__ import annotations

import os
import pytest
from types import SimpleNamespace

from trading_platform.v390.egress_boundary import (
    EgressBoundaryErrorV390,
    EgressDecisionV390,
    EgressPolicyV390,
    EgressTransportV390,
    TestnetEgressAuthorityV390,
)


def test_policy_allows_exact_testnet_rest_host():
    p = EgressPolicyV390()
    assert p.decide("https://testnet.binancefuture.com/fapi/v1/time") is EgressDecisionV390.ALLOW


def test_policy_denies_mainnet_and_unknown_hosts():
    p = EgressPolicyV390()
    assert p.decide("https://fapi.binance.com/fapi/v1/time") is EgressDecisionV390.DENY
    assert p.decide("https://evil.example/fapi/v1/time") is EgressDecisionV390.DENY


def test_policy_requires_https_and_default_port():
    p = EgressPolicyV390()
    assert p.decide("http://testnet.binancefuture.com/fapi/v1/time") is EgressDecisionV390.DENY
    assert p.decide("https://testnet.binancefuture.com:444/fapi/v1/time") is EgressDecisionV390.DENY


def test_policy_denies_embedded_userinfo():
    p = EgressPolicyV390()
    assert p.decide("https://user:pass@testnet.binancefuture.com/fapi/v1/time") is EgressDecisionV390.DENY


def test_websocket_allowlist_is_separate():
    p = EgressPolicyV390()
    assert p.decide("wss://fstream.binancefuture.com/private", websocket=True) is EgressDecisionV390.ALLOW
    assert p.decide("wss://testnet.binancefuture.com/private", websocket=True) is EgressDecisionV390.DENY


def test_ambient_proxy_is_blocked():
    p = EgressPolicyV390()
    with pytest.raises(EgressBoundaryErrorV390, match="AMBIENT_PROXY_CONFIGURATION_BLOCKED"):
        p.assert_no_ambient_proxy({"HTTPS_PROXY": "http://proxy.example:8080"})


def test_no_proxy_variables_allows_constructor():
    EgressTransportV390(environ={"PATH": "/usr/bin"})


def test_transport_rechecks_proxy_on_each_request(monkeypatch):
    tr = EgressTransportV390(environ={})
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    with pytest.raises(EgressBoundaryErrorV390, match="AMBIENT_PROXY_CONFIGURATION_BLOCKED"):
        tr.request("GET", "https://testnet.binancefuture.com/fapi/v1/time")


def test_transport_rechecks_exact_target(monkeypatch):
    tr = EgressTransportV390(environ={})
    with pytest.raises(EgressBoundaryErrorV390, match="TESTNET_EGRESS_TARGET_DENIED"):
        tr.request("GET", "https://fapi.binance.com/fapi/v1/time")


def test_authority_payload_is_safe_and_non_secret():
    auth = TestnetEgressAuthorityV390(environ={})
    payload = auth.authorization_payload(endpoint="https://testnet.binancefuture.com")
    assert payload == {
        "environment": "TESTNET",
        "endpoint_host": "testnet.binancefuture.com",
        "endpoint_scheme": "https",
        "ambient_proxy": "BLOCKED",
        "redirects": "BLOCKED",
    }
    assert "secret" not in str(payload).lower()


def test_authority_blocks_proxy_before_endpoint_release():
    auth = TestnetEgressAuthorityV390(environ={"ALL_PROXY": "http://proxy.example"})
    with pytest.raises(EgressBoundaryErrorV390, match="AMBIENT_PROXY_CONFIGURATION_BLOCKED"):
        auth.authorize_rest("https://testnet.binancefuture.com")


def test_redirect_handler_fails_closed():
    from trading_platform.v390.egress_boundary import _NoRedirectHandler
    with pytest.raises(EgressBoundaryErrorV390, match="TESTNET_REDIRECT_BLOCKED"):
        _NoRedirectHandler().redirect_request(SimpleNamespace(), SimpleNamespace(), 302, "Found", {}, "https://fapi.binance.com")


def test_transport_rejects_non_mapping_response(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'[]'
    class FakeOpener:
        def open(self, req, timeout): return FakeResponse()
    tr = EgressTransportV390(environ={})
    tr._opener = FakeOpener()
    with pytest.raises(ValueError, match="NON_OBJECT_JSON"):
        tr.request("GET", "https://testnet.binancefuture.com/fapi/v1/time")


def test_policy_rejects_alternate_testnet_rest_host():
    with pytest.raises(EgressBoundaryErrorV390, match="REST_HOST_NOT_EXACT_TESTNET"):
        EgressPolicyV390(rest_host="fstream.binancefuture.com").validate()

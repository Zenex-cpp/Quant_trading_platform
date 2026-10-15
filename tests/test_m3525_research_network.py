from pathlib import Path

import pytest

from trading_platform.ops.network_policy import (
    NetworkDecision,
    RESEARCH_NETWORK_POLICY,
    ResearchNetworkPolicy,
    assert_research_endpoint_allowed,
)


def test_research_policy_is_network_isolated_by_default():
    assert RESEARCH_NETWORK_POLICY.decide("https://example.org") is NetworkDecision.DENY
    assert RESEARCH_NETWORK_POLICY.decide("https://api.binance.com") is NetworkDecision.DENY
    assert RESEARCH_NETWORK_POLICY.decide("wss://ws-fapi.binance.com") is NetworkDecision.DENY


def test_research_policy_cannot_be_configured_with_production_hosts():
    with pytest.raises(ValueError, match="RESEARCH_PRODUCTION_HOST_CONFIGURED"):
        ResearchNetworkPolicy(allowed_hosts=frozenset({"api.binance.com"}))
    with pytest.raises(ValueError, match="RESEARCH_PRODUCTION_HOST_CONFIGURED"):
        ResearchNetworkPolicy(allowed_hosts=frozenset({"foo.binance.com"}))


def test_research_policy_allows_explicit_non_production_host_only():
    p = ResearchNetworkPolicy(allowed_hosts=frozenset({"research.example.org"}))
    assert p.decide("https://research.example.org/resource") is NetworkDecision.ALLOW
    assert p.decide("https://other.example.org/resource") is NetworkDecision.DENY
    with pytest.raises(PermissionError, match="RESEARCH_NETWORK_POLICY_DENIED"):
        p.assert_allowed("https://api.binance.com/fapi/v1/order")


def test_research_endpoint_helper_is_fail_closed():
    with pytest.raises(PermissionError, match="RESEARCH_NETWORK_POLICY_DENIED"):
        assert_research_endpoint_allowed("https://api.binance.com/fapi/v1/order")
    with pytest.raises(PermissionError, match="RESEARCH_NETWORK_POLICY_DENIED"):
        assert_research_endpoint_allowed("https://research.example.org")


def test_research_package_has_no_direct_network_client_surface():
    forbidden_tokens = (
        "import requests",
        "import httpx",
        "import socket",
        "import websocket",
        "from urllib.request import",
        "import aiohttp",
        "urlopen(",
    )
    production_tokens = tuple(
        h for h in (
            "api.binance.com",
            "fapi.binance.com",
            "dapi.binance.com",
            "fstream.binance.com",
            "ws-fapi.binance.com",
        )
    )
    root = Path("src/trading_platform/research")
    offenders = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        for token in forbidden_tokens + production_tokens:
            if token in text:
                offenders.append(f"{path}:{token}")
    assert offenders == []

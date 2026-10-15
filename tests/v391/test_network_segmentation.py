from __future__ import annotations

import pytest

from trading_platform.v391.network_segmentation import (
    DEFAULT_ALLOWED_HOSTS_V391,
    NetworkSegmentationPolicyV391,
    NetworkZoneV391,
    SegmentationBoundaryErrorV391,
    SegmentationDecisionV391,
)


def test_default_policy_is_deny_by_default_and_validates():
    p = NetworkSegmentationPolicyV391()
    p.validate()
    assert p.deny_by_default is True


def test_research_cannot_reach_production_or_testnet():
    p = NetworkSegmentationPolicyV391()
    assert p.decide(NetworkZoneV391.RESEARCH, "https://fapi.binance.com/fapi/v1/time") is SegmentationDecisionV391.DENY
    assert p.decide(NetworkZoneV391.RESEARCH, "https://testnet.binancefuture.com/fapi/v1/time") is SegmentationDecisionV391.DENY


def test_testnet_zone_allows_only_testnet_hosts():
    p = NetworkSegmentationPolicyV391()
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "https://testnet.binancefuture.com/fapi/v1/time") is SegmentationDecisionV391.ALLOW
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "wss://fstream.binancefuture.com/private") is SegmentationDecisionV391.ALLOW
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "https://fapi.binance.com/fapi/v1/time") is SegmentationDecisionV391.DENY


def test_production_zone_cannot_reach_testnet():
    p = NetworkSegmentationPolicyV391()
    assert p.decide(NetworkZoneV391.PRODUCTION_TRADING, "https://fapi.binance.com/fapi/v1/time") is SegmentationDecisionV391.ALLOW
    assert p.decide(NetworkZoneV391.PRODUCTION_TRADING, "https://testnet.binancefuture.com/fapi/v1/time") is SegmentationDecisionV391.DENY


def test_non_tls_and_unknown_hosts_are_denied():
    p = NetworkSegmentationPolicyV391()
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "http://testnet.binancefuture.com/fapi/v1/time") is SegmentationDecisionV391.DENY
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "https://evil.example") is SegmentationDecisionV391.DENY


def test_wildcards_are_rejected():
    bad = dict(DEFAULT_ALLOWED_HOSTS_V391)
    bad[NetworkZoneV391.TESTNET_EXECUTION] = frozenset({"*.binancefuture.com"})
    with pytest.raises(SegmentationBoundaryErrorV391, match="NON_EXACT_EGRESS_HOST"):
        NetworkSegmentationPolicyV391(allowed_hosts=bad).validate()


def test_research_production_host_configuration_is_rejected():
    bad = dict(DEFAULT_ALLOWED_HOSTS_V391)
    bad[NetworkZoneV391.RESEARCH] = frozenset({"fapi.binance.com"})
    with pytest.raises(SegmentationBoundaryErrorV391, match="RESEARCH_PRODUCTION_ENDPOINT_CONFIGURED"):
        NetworkSegmentationPolicyV391(allowed_hosts=bad).validate()


def test_testnet_zone_cannot_invent_endpoint():
    bad = dict(DEFAULT_ALLOWED_HOSTS_V391)
    bad[NetworkZoneV391.TESTNET_EXECUTION] = frozenset({"unknown.testnet.example"})
    with pytest.raises(SegmentationBoundaryErrorV391, match="TESTNET_ZONE_ENDPOINT_NOT_ALLOWLISTED"):
        NetworkSegmentationPolicyV391(allowed_hosts=bad).validate()


def test_production_zone_cannot_invent_endpoint():
    bad = dict(DEFAULT_ALLOWED_HOSTS_V391)
    bad[NetworkZoneV391.PRODUCTION_TRADING] = frozenset({"prod.example"})
    with pytest.raises(SegmentationBoundaryErrorV391, match="PRODUCTION_ZONE_ENDPOINT_NOT_ALLOWLISTED"):
        NetworkSegmentationPolicyV391(allowed_hosts=bad).validate()


def test_tls_scheme_required_for_allows():
    p = NetworkSegmentationPolicyV391()
    assert p.decide(NetworkZoneV391.TESTNET_EXECUTION, "ftp://testnet.binancefuture.com") is SegmentationDecisionV391.DENY


def test_review_payload_is_non_secret_and_marks_infrastructure_unverified():
    payload = NetworkSegmentationPolicyV391().review_payload()
    assert payload["infrastructure_proof"] == "NOT_VERIFIED"
    assert "secret" not in str(payload).lower()
    assert payload["research_to_production"] == "DENY"

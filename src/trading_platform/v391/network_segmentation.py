"""V3.91 network-segmentation contract.

This module models the infrastructure-level egress policy required by Master
Prompt M25. It is deliberately declarative and fail-closed. It does not claim
that application tests prove an actual host firewall, VPC/NACL, container
NetworkPolicy, routing table, or cloud control-plane configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from dataclasses import field
from urllib.parse import urlparse

from trading_platform.ops.network_policy import PRODUCTION_HOSTS, TESTNET_HOSTS


class SegmentationDecisionV391(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class SegmentationBoundaryErrorV391(PermissionError):
    __test__ = False


class NetworkZoneV391(str, Enum):
    RESEARCH = "RESEARCH"
    TESTNET_EXECUTION = "TESTNET_EXECUTION"
    PRODUCTION_TRADING = "PRODUCTION_TRADING"


DEFAULT_ALLOWED_HOSTS_V391: dict[NetworkZoneV391, frozenset[str]] = {
    NetworkZoneV391.RESEARCH: frozenset(),
    NetworkZoneV391.TESTNET_EXECUTION: frozenset(TESTNET_HOSTS),
    NetworkZoneV391.PRODUCTION_TRADING: frozenset(PRODUCTION_HOSTS),
}


@dataclass(frozen=True)
class NetworkSegmentationPolicyV391:
    """Machine-checkable deny-by-default segmentation policy."""

    deny_by_default: bool = True
    allowed_hosts: Mapping[NetworkZoneV391, frozenset[str]] = field(default_factory=lambda: DEFAULT_ALLOWED_HOSTS_V391.copy())
    production_hosts: frozenset[str] = frozenset(PRODUCTION_HOSTS)
    testnet_hosts: frozenset[str] = frozenset(TESTNET_HOSTS)

    def validate(self) -> None:
        if not self.deny_by_default:
            raise SegmentationBoundaryErrorV391("SEGMENTATION_MUST_BE_DENY_BY_DEFAULT")
        normalized_prod = {h.lower().rstrip(".") for h in self.production_hosts}
        normalized_test = {h.lower().rstrip(".") for h in self.testnet_hosts}
        if normalized_prod & normalized_test:
            raise SegmentationBoundaryErrorV391("PRODUCTION_TESTNET_HOST_SET_OVERLAP")
        for zone in NetworkZoneV391:
            hosts = self.allowed_hosts.get(zone, frozenset())
            for host in hosts:
                canonical = host.lower().rstrip(".")
                if not canonical or "*" in canonical or "/" in canonical:
                    raise SegmentationBoundaryErrorV391("NON_EXACT_EGRESS_HOST")
                if zone is NetworkZoneV391.RESEARCH:
                    if canonical in normalized_prod or canonical.endswith(".binance.com") or canonical.endswith(".binance.us"):
                        raise SegmentationBoundaryErrorV391("RESEARCH_PRODUCTION_ENDPOINT_CONFIGURED")
                elif zone is NetworkZoneV391.TESTNET_EXECUTION:
                    if canonical not in normalized_test:
                        raise SegmentationBoundaryErrorV391("TESTNET_ZONE_ENDPOINT_NOT_ALLOWLISTED")
                    if canonical in normalized_prod:
                        raise SegmentationBoundaryErrorV391("TESTNET_PRODUCTION_ENDPOINT_OVERLAP")
                elif zone is NetworkZoneV391.PRODUCTION_TRADING:
                    if canonical not in normalized_prod:
                        raise SegmentationBoundaryErrorV391("PRODUCTION_ZONE_ENDPOINT_NOT_ALLOWLISTED")
                    if canonical in normalized_test:
                        raise SegmentationBoundaryErrorV391("PRODUCTION_TESTNET_ENDPOINT_OVERLAP")

    @staticmethod
    def _host(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        return (parsed.hostname or "").lower().rstrip(".")

    def decide(self, source_zone: NetworkZoneV391, endpoint: str) -> SegmentationDecisionV391:
        self.validate()
        if source_zone not in NetworkZoneV391:
            return SegmentationDecisionV391.DENY
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"https", "wss"}:
            return SegmentationDecisionV391.DENY
        host = self._host(endpoint)
        if not host:
            return SegmentationDecisionV391.DENY
        if source_zone is NetworkZoneV391.RESEARCH:
            return SegmentationDecisionV391.DENY
        if host in {h.lower().rstrip(".") for h in self.allowed_hosts.get(source_zone, frozenset())}:
            return SegmentationDecisionV391.ALLOW
        return SegmentationDecisionV391.DENY

    def assert_allowed(self, source_zone: NetworkZoneV391, endpoint: str) -> None:
        if self.decide(source_zone, endpoint) is not SegmentationDecisionV391.ALLOW:
            raise SegmentationBoundaryErrorV391("NETWORK_SEGMENTATION_DENIED")

    def review_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": "V391_NETWORK_SEGMENTATION_POLICY_1",
            "deny_by_default": self.deny_by_default,
            "zones": {
                zone.value: sorted(hosts)
                for zone, hosts in self.allowed_hosts.items()
            },
            "research_to_production": "DENY",
            "research_to_testnet": "DENY",
            "testnet_to_production": "DENY",
            "production_to_testnet": "DENY",
            "wildcards": "DENY",
            "credential_release": "OUTSIDE_POLICY_SCOPE",
            "infrastructure_proof": "NOT_VERIFIED",
        }

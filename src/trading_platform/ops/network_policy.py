from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

class NetworkDecision(str, Enum):
    ALLOW='ALLOW'; DENY='DENY'

PRODUCTION_HOSTS={
    'fapi.binance.com','dapi.binance.com','api.binance.com',
    'ws-fapi.binance.com','fstream.binance.com','fstream-auth.binance.com',
}
TESTNET_HOSTS={'testnet.binancefuture.com','fstream.binancefuture.com'}

@dataclass(frozen=True)
class NetworkPolicy:
    environment: str
    allowed_hosts: frozenset[str]
    tls_required: bool = True

    def decide(self, endpoint: str) -> NetworkDecision:
        u=urlparse(endpoint)
        if self.tls_required and u.scheme not in {'https','wss'}:
            return NetworkDecision.DENY
        host=(u.hostname or '').lower()
        if host in PRODUCTION_HOSTS:
            return NetworkDecision.DENY
        if host not in self.allowed_hosts:
            return NetworkDecision.DENY
        return NetworkDecision.ALLOW

    def assert_allowed(self, endpoint: str) -> None:
        if self.decide(endpoint) is not NetworkDecision.ALLOW:
            raise PermissionError('NETWORK_POLICY_DENIED')

TESTNET_POLICY=NetworkPolicy('TESTNET', frozenset(TESTNET_HOSTS))


@dataclass(frozen=True)
class ResearchNetworkPolicy:
    """Research egress boundary. Production trading endpoints are never routable.

    The default allowlist is empty by design: Research is network-isolated unless an
    explicitly non-production endpoint is approved. Production endpoint configuration
    is rejected at construction time, providing a fail-closed boundary independent of
    role checks elsewhere in the system.
    """

    allowed_hosts: frozenset[str] = frozenset()
    tls_required: bool = True

    def __post_init__(self) -> None:
        blocked = sorted(h.lower().rstrip('.') for h in self.allowed_hosts if h.lower().rstrip('.') in PRODUCTION_HOSTS or h.lower().rstrip('.').endswith('.binance.com') or h.lower().rstrip('.').endswith('.binance.us'))
        if blocked:
            raise ValueError("RESEARCH_PRODUCTION_HOST_CONFIGURED")

    def decide(self, endpoint: str) -> NetworkDecision:
        u = urlparse(endpoint)
        if self.tls_required and u.scheme not in {"https", "wss"}:
            return NetworkDecision.DENY
        host = (u.hostname or "").lower().rstrip('.')
        if host in PRODUCTION_HOSTS or host.endswith(".binance.com") or host.endswith(".binance.us"):
            return NetworkDecision.DENY
        if host not in {h.lower().rstrip('.') for h in self.allowed_hosts}:
            return NetworkDecision.DENY
        return NetworkDecision.ALLOW

    def assert_allowed(self, endpoint: str) -> None:
        if self.decide(endpoint) is not NetworkDecision.ALLOW:
            raise PermissionError("RESEARCH_NETWORK_POLICY_DENIED")


RESEARCH_NETWORK_POLICY = ResearchNetworkPolicy()


def assert_research_endpoint_allowed(endpoint: str) -> None:
    RESEARCH_NETWORK_POLICY.assert_allowed(endpoint)

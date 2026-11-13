from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Any


class Capability(str, Enum):
    RESEARCH = "RESEARCH"
    TRAINING = "TRAINING"
    BACKTEST = "BACKTEST"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    PRODUCTION_TRADING = "PRODUCTION_TRADING"
    DEPLOYMENT = "DEPLOYMENT"
    CONFIGURATION = "CONFIGURATION"
    SECURITY_ADMIN = "SECURITY_ADMIN"


# Roles are deliberately capabilities with a small, explicit set of grants.
# This keeps the existing Research workflow (research, training, backtest)
# while requiring separate authority for deployment, configuration, and live
# production trading. SECURITY_ADMIN may manage configuration, but does not
# itself grant deployment or production trading.
ROLE_CAPABILITIES = MappingProxyType(
    {
        Capability.RESEARCH: frozenset(
            {Capability.RESEARCH, Capability.TRAINING, Capability.BACKTEST}
        ),
        Capability.TRAINING: frozenset({Capability.TRAINING}),
        Capability.BACKTEST: frozenset({Capability.BACKTEST}),
        Capability.SHADOW: frozenset({Capability.SHADOW}),
        Capability.CANARY: frozenset({Capability.CANARY}),
        Capability.PRODUCTION_TRADING: frozenset({Capability.PRODUCTION_TRADING}),
        Capability.DEPLOYMENT: frozenset({Capability.DEPLOYMENT}),
        Capability.CONFIGURATION: frozenset({Capability.CONFIGURATION}),
        Capability.SECURITY_ADMIN: frozenset(
            {Capability.SECURITY_ADMIN, Capability.CONFIGURATION}
        ),
    }
)


def capability_matrix() -> tuple[tuple[str, str, str], ...]:
    """Return the complete role/capability decision matrix in stable order."""
    return tuple(
        (
            role.value,
            capability.value,
            "ALLOW" if capability in ROLE_CAPABILITIES[role] else "DENY",
        )
        for role in Capability
        for capability in Capability
    )


def assert_capability(role: Any, capability: Any) -> None:
    """Raise PermissionError unless the known role has the requested grant.

    Invalid role and capability inputs fail closed. Resource ownership and
    object-level scope are checked by the resource-owning service; this helper
    only decides the role/capability boundary.
    """
    if not isinstance(role, str):
        raise PermissionError("ROLE_UNKNOWN_FORBIDDEN")
    normalized_role = role.strip().upper()
    try:
        role_capability = Capability(normalized_role)
    except ValueError:
        raise PermissionError("ROLE_UNKNOWN_FORBIDDEN") from None

    if not isinstance(capability, Capability):
        raise PermissionError("CAPABILITY_INVALID_FORBIDDEN")
    if capability not in ROLE_CAPABILITIES[role_capability]:
        if role_capability is Capability.RESEARCH and capability in {
            Capability.PRODUCTION_TRADING,
            Capability.DEPLOYMENT,
            Capability.CONFIGURATION,
            Capability.SECURITY_ADMIN,
            Capability.CANARY,
        }:
            raise PermissionError("RESEARCH_TO_PRODUCTION_FORBIDDEN")
        raise PermissionError("ROLE_CAPABILITY_NOT_GRANTED")

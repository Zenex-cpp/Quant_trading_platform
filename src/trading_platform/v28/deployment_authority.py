from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from threading import local
from uuid import uuid4
from typing import Iterator


class ActivationCapabilityError(RuntimeError):
    """An activation capability is absent, invalid, expired, or already consumed."""


_CAPABILITY_SECRET = object()
_CONTEXT = local()


@dataclass(frozen=True)
class DeploymentActivationCapability:
    deployment_id: str
    activation_fingerprint: str
    target_mode: str
    effective_risk: Decimal
    valid_from: datetime
    expires_at: datetime
    capability_id: str
    _secret: object

    @property
    def valid(self) -> bool:
        return self._secret is _CAPABILITY_SECRET

    def active_at(self, now: datetime) -> bool:
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ActivationCapabilityError("ACTIVATION_CAPABILITY_TIMEZONE_REQUIRED")
        now_utc = now.astimezone(timezone.utc)
        return self.valid and self.valid_from <= now_utc < self.expires_at

    @classmethod
    def build(
        cls,
        *,
        deployment_id: str,
        activation_fingerprint: str,
        target_mode: str,
        effective_risk: Decimal,
        valid_from: datetime,
        expires_at: datetime,
    ) -> "DeploymentActivationCapability":
        if not deployment_id or not activation_fingerprint or not target_mode:
            raise ActivationCapabilityError("ACTIVATION_CAPABILITY_IDENTIFIERS_REQUIRED")
        if effective_risk < 0 or not effective_risk.is_finite():
            raise ActivationCapabilityError("ACTIVATION_CAPABILITY_RISK_INVALID")
        if valid_from.tzinfo is None or expires_at.tzinfo is None:
            raise ActivationCapabilityError("ACTIVATION_CAPABILITY_TIMEZONE_REQUIRED")
        vf = valid_from.astimezone(timezone.utc)
        ex = expires_at.astimezone(timezone.utc)
        if ex <= vf:
            raise ActivationCapabilityError("ACTIVATION_CAPABILITY_WINDOW_INVALID")
        payload = {
            "deployment_id": deployment_id,
            "activation_fingerprint": activation_fingerprint,
            "target_mode": target_mode,
            "effective_risk": str(effective_risk),
            "valid_from": vf.isoformat(),
            "expires_at": ex.isoformat(),
        }
        capability_id = sha256(
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + ":" + uuid4().hex).encode()
        ).hexdigest()
        return cls(
            deployment_id=deployment_id,
            activation_fingerprint=activation_fingerprint,
            target_mode=target_mode,
            effective_risk=effective_risk,
            valid_from=vf,
            expires_at=ex,
            capability_id=capability_id,
            _secret=_CAPABILITY_SECRET,
        )


def _issue_activation_capability(
    *,
    deployment_id: str,
    activation_fingerprint: str,
    target_mode: str,
    effective_risk: Decimal,
    valid_from: datetime,
    expires_at: datetime,
) -> DeploymentActivationCapability:
    """Internal issuer. Production code must obtain capability through V3.25/V3.26 authority."""
    return DeploymentActivationCapability.build(
        deployment_id=deployment_id,
        activation_fingerprint=activation_fingerprint,
        target_mode=target_mode,
        effective_risk=effective_risk,
        valid_from=valid_from,
        expires_at=expires_at,
    )


def _consumed_ids() -> set[str]:
    value = getattr(_CONTEXT, "consumed", None)
    if value is None:
        value = set()
        _CONTEXT.consumed = value
    return value


@contextmanager
def activation_capability_context(capability: DeploymentActivationCapability) -> Iterator[None]:
    if not isinstance(capability, DeploymentActivationCapability) or not capability.valid:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_INVALID")
    previous = getattr(_CONTEXT, "capability", None)
    _CONTEXT.capability = capability
    try:
        yield
    finally:
        _CONTEXT.capability = previous


def current_activation_capability() -> DeploymentActivationCapability | None:
    capability = getattr(_CONTEXT, "capability", None)
    return capability if isinstance(capability, DeploymentActivationCapability) else None


def assert_activation_capability(
    *,
    deployment_id: str,
    target_mode: str,
    allocated_risk: Decimal,
    now: datetime,
    activation_fingerprint: str | None = None,
) -> DeploymentActivationCapability:
    capability = current_activation_capability()
    if capability is None or not capability.valid:
        raise ActivationCapabilityError("DEPLOYMENT_ACTIVATION_AUTHORITY_REQUIRED")
    if capability.capability_id in _consumed_ids():
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_ALREADY_CONSUMED")
    if not capability.active_at(now):
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_EXPIRED")
    if capability.deployment_id != deployment_id:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_DEPLOYMENT_MISMATCH")
    if capability.target_mode != target_mode:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_TARGET_MISMATCH")
    if activation_fingerprint is not None and capability.activation_fingerprint != activation_fingerprint:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_FINGERPRINT_MISMATCH")
    if allocated_risk > capability.effective_risk:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_RISK_BREACH")
    return capability


def consume_activation_capability(capability: DeploymentActivationCapability) -> None:
    current = current_activation_capability()
    if current is not capability:
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_CONTEXT_MISMATCH")
    if capability.capability_id in _consumed_ids():
        raise ActivationCapabilityError("ACTIVATION_CAPABILITY_ALREADY_CONSUMED")
    _consumed_ids().add(capability.capability_id)

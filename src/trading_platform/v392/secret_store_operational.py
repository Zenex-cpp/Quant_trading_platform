"""V3.92 secret-store operational contract.

This module is an application-level gate. It does not claim proof of an
external vault/KMS deployment. Production activation requires an attested,
non-development secret backend; otherwise the gate fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping


class SecretStoreBoundaryErrorV392(PermissionError):
    __test__ = False


class SecretStoreBackendV392(str, Enum):
    EXTERNAL_VAULT = "EXTERNAL_VAULT"
    KMS_WRAPPED = "KMS_WRAPPED"
    IN_MEMORY_DEV = "IN_MEMORY_DEV"
    ENVIRONMENT = "ENVIRONMENT"


class SecretLeaseStateV392(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CONSUMED = "CONSUMED"


@dataclass(frozen=True)
class SecretStoreAttestationV392:
    backend: SecretStoreBackendV392
    backend_id: str
    backend_version: str
    attested_at_ms: int
    expires_at_ms: int
    configuration_fingerprint: str
    reviewer_id: str
    review_reference: str

    def validate(self, *, now_ms: int) -> None:
        if not self.backend_id or not self.backend_version or not self.configuration_fingerprint:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_ATTESTATION_INVALID")
        if not self.reviewer_id or not self.review_reference:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_REVIEW_REFERENCE_MISSING")
        if self.expires_at_ms <= self.attested_at_ms:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_ATTESTATION_WINDOW_INVALID")
        if now_ms < self.attested_at_ms or now_ms >= self.expires_at_ms:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_ATTESTATION_EXPIRED")

    def safe_payload(self) -> dict[str, object]:
        return {
            "backend": self.backend.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "attested_at_ms": self.attested_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "configuration_fingerprint": self.configuration_fingerprint,
            "reviewer_id": self.reviewer_id,
            "review_reference": self.review_reference,
        }


@dataclass(frozen=True)
class SecretLeaseV392:
    lease_id: str
    credential_id: str
    version: str
    backend: SecretStoreBackendV392
    issued_at_ms: int
    expires_at_ms: int
    credential_fingerprint: str
    state: SecretLeaseStateV392 = SecretLeaseStateV392.ISSUED

    def validate(self, *, now_ms: int, max_ttl_ms: int) -> None:
        if not self.lease_id or not self.credential_id or not self.version or not self.credential_fingerprint:
            raise SecretStoreBoundaryErrorV392("SECRET_LEASE_INVALID")
        if self.expires_at_ms <= self.issued_at_ms:
            raise SecretStoreBoundaryErrorV392("SECRET_LEASE_WINDOW_INVALID")
        if self.expires_at_ms - self.issued_at_ms > max_ttl_ms:
            raise SecretStoreBoundaryErrorV392("SECRET_LEASE_TTL_EXCEEDS_POLICY")
        if self.state in {SecretLeaseStateV392.EXPIRED, SecretLeaseStateV392.REVOKED, SecretLeaseStateV392.CONSUMED}:
            raise SecretStoreBoundaryErrorV392("SECRET_LEASE_NOT_ACTIVE")
        if now_ms < self.issued_at_ms or now_ms >= self.expires_at_ms:
            raise SecretStoreBoundaryErrorV392("SECRET_LEASE_EXPIRED")

    def safe_payload(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "credential_id": self.credential_id,
            "version": self.version,
            "backend": self.backend.value,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "credential_fingerprint": self.credential_fingerprint,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class SecretStoreOperationalPolicyV392:
    production_backend: SecretStoreBackendV392 = SecretStoreBackendV392.EXTERNAL_VAULT
    allow_environment_production: bool = False
    allow_in_memory_production: bool = False
    require_attestation: bool = True
    require_review_reference: bool = True
    max_lease_ttl_ms: int = 3_600_000

    def validate(self) -> None:
        if self.max_lease_ttl_ms <= 0:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_MAX_TTL_INVALID")
        if self.production_backend in {SecretStoreBackendV392.ENVIRONMENT, SecretStoreBackendV392.IN_MEMORY_DEV}:
            raise SecretStoreBoundaryErrorV392("PRODUCTION_SECRET_BACKEND_NOT_OPERATIONAL")
        if self.allow_environment_production or self.allow_in_memory_production:
            raise SecretStoreBoundaryErrorV392("PRODUCTION_SECRET_FALLBACK_FORBIDDEN")


@dataclass(frozen=True)
class SecretStoreReviewDecisionV392:
    allowed: bool
    reason: str
    backend: SecretStoreBackendV392
    credential_id: str
    version: str
    lease_id: str | None
    evidence_status: str

    def safe_payload(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "backend": self.backend.value,
            "credential_id": self.credential_id,
            "version": self.version,
            "lease_id": self.lease_id,
            "evidence_status": self.evidence_status,
        }


def configuration_fingerprint(configuration: Mapping[str, Any]) -> str:
    """Stable fingerprint of non-secret backend configuration only."""
    forbidden = {"api_key", "api_secret", "secret", "password", "token", "private_key"}
    if any(str(k).lower() in forbidden for k in configuration):
        raise SecretStoreBoundaryErrorV392("SECRET_MATERIAL_IN_REVIEW_CONFIGURATION")
    canonical = "|".join(f"{k}={configuration[k]}" for k in sorted(configuration))
    return sha256(canonical.encode("utf-8")).hexdigest()


def assert_production_secret_store_ready(
    *,
    policy: SecretStoreOperationalPolicyV392,
    attestation: SecretStoreAttestationV392 | None,
    lease: SecretLeaseV392,
    now_ms: int,
) -> SecretStoreReviewDecisionV392:
    """Return an admission decision; never returns raw secret material."""
    try:
        policy.validate()
        if lease.backend is not policy.production_backend:
            raise SecretStoreBoundaryErrorV392("SECRET_STORE_BACKEND_MISMATCH")
        if policy.require_attestation:
            if attestation is None:
                raise SecretStoreBoundaryErrorV392("SECRET_STORE_ATTESTATION_REQUIRED")
            attestation.validate(now_ms=now_ms)
            if attestation.backend is not lease.backend:
                raise SecretStoreBoundaryErrorV392("SECRET_STORE_ATTESTATION_BACKEND_MISMATCH")
        lease.validate(now_ms=now_ms, max_ttl_ms=policy.max_lease_ttl_ms)
        return SecretStoreReviewDecisionV392(
            True,
            "SECRET_STORE_READY",
            lease.backend,
            lease.credential_id,
            lease.version,
            lease.lease_id,
            "VERIFIED_IN_PROCESS_ONLY",
        )
    except SecretStoreBoundaryErrorV392 as exc:
        return SecretStoreReviewDecisionV392(
            False,
            str(exc),
            lease.backend,
            lease.credential_id,
            lease.version,
            lease.lease_id,
            "NOT_VERIFIED",
        )


def assert_no_secret_material(value: Any) -> None:
    """Reject review/evidence payloads carrying likely secret material."""
    forbidden = {"api_key", "apikey", "api_secret", "apisecret", "secret", "password", "token", "private_key"}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in forbidden:
                raise SecretStoreBoundaryErrorV392("SECRET_MATERIAL_IN_EVIDENCE")
            assert_no_secret_material(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            assert_no_secret_material(item)
    elif hasattr(value, "__dict__"):
        for key, item in vars(value).items():
            if str(key).lower() in forbidden:
                raise SecretStoreBoundaryErrorV392("SECRET_MATERIAL_IN_EVIDENCE")
            assert_no_secret_material(item)

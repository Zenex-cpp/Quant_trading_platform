"""Production credential vault and research visibility boundary.

Production credentials are runtime-only values.  Research receives neither the
credential material nor an executable resolver.  The vault exposes only opaque
references/metadata until a PRODUCTION_TRADING actor explicitly resolves one.
All lifecycle decisions are auditable without persisting secret material.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from collections.abc import Mapping, Sequence
from typing import Any

from trading_platform.v21.event_store import EventStore
from trading_platform.security.permissions import Capability, assert_capability
from trading_platform.v35.binance_execution import RuntimeCredentialValues


class ProductionCredentialAccessError(PermissionError):
    pass


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class ProductionCredentialRef:
    credential_id: str
    version: str
    valid_from_ms: int
    expires_at_ms: int
    fingerprint: str

    def validate(self, *, now_ms: int) -> None:
        if not self.credential_id or not self.version or not self.fingerprint:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID")
        if self.expires_at_ms <= self.valid_from_ms:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_WINDOW_INVALID")
        if now_ms < self.valid_from_ms or now_ms >= self.expires_at_ms:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_EXPIRED")


@dataclass(frozen=True)
class ProductionCredentialMetadata:
    credential_id: str
    version: str
    valid_from_ms: int
    expires_at_ms: int
    status: CredentialStatus
    fingerprint: str


@dataclass(frozen=True)
class _CredentialRecord:
    ref: ProductionCredentialRef
    api_key: str
    api_secret: bytes
    status: CredentialStatus


class ProductionCredentialVault:
    """In-memory secret store with auditable, role-gated resolution.

    Secret material is deliberately absent from event payloads and metadata.
    The in-memory record is never exposed through a public accessor.
    """

    REGISTER_EVENT = "PRODUCTION_CREDENTIAL_REGISTERED"
    RESOLVE_EVENT = "PRODUCTION_CREDENTIAL_RESOLVED"
    DENY_EVENT = "PRODUCTION_CREDENTIAL_RESOLUTION_DENIED"
    REVOKE_EVENT = "PRODUCTION_CREDENTIAL_REVOKED"

    def __init__(self, *, store: EventStore | None = None):
        self.__store = store or EventStore()
        self.__records: dict[tuple[str, str], _CredentialRecord] = {}

    @property
    def store(self) -> EventStore:
        return self.__store

    def register(
        self,
        *,
        credential_id: str,
        version: str,
        api_key: str,
        api_secret: bytes,
        valid_from_ms: int,
        ttl_ms: int = 3_600_000,
        actor_role: str,
    ) -> ProductionCredentialRef:
        self._assert_management_access(actor_role)
        if not credential_id or not version or not api_key or not api_secret:
            raise ValueError("PRODUCTION_CREDENTIAL_MATERIAL_REQUIRED")
        if valid_from_ms < 0 or ttl_ms <= 0:
            raise ValueError("PRODUCTION_CREDENTIAL_WINDOW_INVALID")
        fingerprint = sha256(api_key.encode() + b"|" + bytes(api_secret)).hexdigest()
        ref = ProductionCredentialRef(
            credential_id, version, valid_from_ms, valid_from_ms + ttl_ms, fingerprint
        )
        key = (credential_id, version)
        event_id = f"production-credential:{credential_id}:{version}"
        payload = {
            "credential_id": credential_id,
            "version": version,
            "valid_from_ms": valid_from_ms,
            "expires_at_ms": ref.expires_at_ms,
            "fingerprint": fingerprint,
            "status": CredentialStatus.ACTIVE.value,
        }
        existing = self.__store.get(event_id)
        if existing is not None and existing.payload != payload:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_ID_CONFLICT")
        if existing is None:
            self.__store.append(
                event_id=event_id,
                occurred_at_ms=valid_from_ms,
                event_type=self.REGISTER_EVENT,
                aggregate_id=credential_id,
                payload=payload,
            )
        record = self.__records.get(key)
        if record is not None and (record.ref != ref or record.api_key != api_key or record.api_secret != bytes(api_secret)):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_ID_CONFLICT")
        self.__records[key] = _CredentialRecord(ref, api_key, bytes(api_secret), CredentialStatus.ACTIVE)
        self.__store.verify_chain()
        return ref

    def rotate(
        self,
        *,
        credential_id: str,
        new_version: str,
        api_key: str,
        api_secret: bytes,
        valid_from_ms: int,
        ttl_ms: int = 3_600_000,
        actor_role: str,
    ) -> ProductionCredentialRef:
        """Register a new version; the old version remains auditable and independently revocable."""
        return self.register(
            credential_id=credential_id,
            version=new_version,
            api_key=api_key,
            api_secret=api_secret,
            valid_from_ms=valid_from_ms,
            ttl_ms=ttl_ms,
            actor_role=actor_role,
        )

    def metadata(self, ref: ProductionCredentialRef) -> ProductionCredentialMetadata:
        record = self.__records.get((ref.credential_id, ref.version))
        if record is None:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
        return ProductionCredentialMetadata(
            record.ref.credential_id,
            record.ref.version,
            record.ref.valid_from_ms,
            record.ref.expires_at_ms,
            record.status,
            record.ref.fingerprint,
        )

    def revoke(self, *, credential_id: str, version: str, now_ms: int, actor_role: str) -> None:
        self._assert_authorized(actor_role)
        key = (credential_id, version)
        record = self.__records.get(key)
        if record is None:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
        if record.status is CredentialStatus.REVOKED:
            return
        self.__records[key] = _CredentialRecord(record.ref, record.api_key, record.api_secret, CredentialStatus.REVOKED)
        self.__store.append(
            event_id=f"production-credential-revoke:{credential_id}:{version}:{now_ms}",
            occurred_at_ms=now_ms,
            event_type=self.REVOKE_EVENT,
            aggregate_id=credential_id,
            payload={"credential_id": credential_id, "version": version, "actor_role": actor_role},
        )
        self.__store.verify_chain()

    def resolve(self, ref: ProductionCredentialRef, *, actor_role: str, now_ms: int) -> RuntimeCredentialValues:
        if actor_role.upper() != Capability.PRODUCTION_TRADING.value:
            self.__audit_deny(ref, actor_role, now_ms, "ROLE_FORBIDDEN")
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        try:
            assert_capability(actor_role, Capability.PRODUCTION_TRADING)
        except PermissionError:
            self.__audit_deny(ref, actor_role, now_ms, "CAPABILITY_FORBIDDEN")
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        ref.validate(now_ms=now_ms)
        record = self.__records.get((ref.credential_id, ref.version))
        if record is None:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
        if record.ref != ref:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_MISMATCH")
        if record.status is not CredentialStatus.ACTIVE:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REVOKED")
        self.__store.append(
            event_id=f"production-credential-resolve:{ref.credential_id}:{ref.version}:{now_ms}:{ref.fingerprint[:12]}",
            occurred_at_ms=now_ms,
            event_type=self.RESOLVE_EVENT,
            aggregate_id=ref.credential_id,
            payload={
                "credential_id": ref.credential_id,
                "version": ref.version,
                "actor_role": actor_role.upper(),
                "fingerprint": ref.fingerprint,
            },
        )
        self.__store.verify_chain()
        return RuntimeCredentialValues(record.api_key, record.api_secret)

    def _assert_management_access(self, actor_role: str) -> None:
        role = actor_role.upper()
        if role not in {Capability.SECURITY_ADMIN.value, Capability.PRODUCTION_TRADING.value}:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        assert_capability(actor_role, Capability.CONFIGURATION)

    def _assert_authorized(self, actor_role: str) -> None:
        if actor_role.upper() != Capability.PRODUCTION_TRADING.value:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        assert_capability(actor_role, Capability.PRODUCTION_TRADING)

    def __audit_deny(self, ref: ProductionCredentialRef, actor_role: str, now_ms: int, reason: str) -> None:
        self.__store.append(
            event_id=f"production-credential-deny:{ref.credential_id}:{ref.version}:{now_ms}:{actor_role}:{reason}",
            occurred_at_ms=now_ms,
            event_type=self.DENY_EVENT,
            aggregate_id=ref.credential_id,
            payload={
                "credential_id": ref.credential_id,
                "version": ref.version,
                "actor_role": actor_role.upper(),
                "reason": reason,
            },
        )
        self.__store.verify_chain()


_CREDENTIAL_KEY_MARKERS = {
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "secret_key",
    "secretkey",
    "private_key",
    "privatekey",
    "credential",
    "credentials",
    "production_credential",
    "production_credentials",
    "access_token",
    "refresh_token",
}


def _looks_like_credential_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    return key.lower().replace("-", "_") in _CREDENTIAL_KEY_MARKERS


def assert_research_safe(value: Any, *, _seen: set[int] | None = None) -> None:
    """Fail closed if production credential material or handles cross research boundaries."""
    seen = _seen or set()
    ident = id(value)
    if ident in seen:
        return
    seen.add(ident)
    if isinstance(value, (RuntimeCredentialValues, ProductionCredentialRef, ProductionCredentialMetadata, ProductionCredentialVault, _CredentialRecord)):
        raise ProductionCredentialAccessError("RESEARCH_PRODUCTION_CREDENTIAL_VISIBILITY_FORBIDDEN")
    if isinstance(value, Mapping):
        for k, v in value.items():
            if _looks_like_credential_key(k):
                raise ProductionCredentialAccessError("RESEARCH_PRODUCTION_CREDENTIAL_VISIBILITY_FORBIDDEN")
            assert_research_safe(v, _seen=seen)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            assert_research_safe(item, _seen=seen)
        return
    if hasattr(value, "__dict__"):
        for k, v in vars(value).items():
            if _looks_like_credential_key(k):
                raise ProductionCredentialAccessError("RESEARCH_PRODUCTION_CREDENTIAL_VISIBILITY_FORBIDDEN")
            assert_research_safe(v, _seen=seen)


def assert_research_arguments(*args: Any, **kwargs: Any) -> None:
    for arg in args:
        assert_research_safe(arg)
    assert_research_safe(kwargs)

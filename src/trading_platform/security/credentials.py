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
from threading import RLock
from typing import Any
import re
from uuid import uuid4

from trading_platform.v21.event_store import EventStore
from trading_platform.security.permissions import Capability, assert_capability
from trading_platform.v35.binance_execution import RuntimeCredentialValues
from trading_platform.security.credential_backends import (
    CredentialBackendError,
    CredentialSecretBackend,
    InMemoryCredentialSecretBackend,
)


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
        if (
            not isinstance(self.credential_id, str)
            or not _CREDENTIAL_IDENTIFIER.fullmatch(self.credential_id)
            or not isinstance(self.version, str)
            or not _CREDENTIAL_IDENTIFIER.fullmatch(self.version)
            or not isinstance(self.fingerprint, str)
            or not _CREDENTIAL_FINGERPRINT.fullmatch(self.fingerprint)
        ):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID")
        if (
            not isinstance(self.valid_from_ms, int)
            or isinstance(self.valid_from_ms, bool)
            or not isinstance(self.expires_at_ms, int)
            or isinstance(self.expires_at_ms, bool)
            or self.expires_at_ms <= self.valid_from_ms
        ):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_WINDOW_INVALID")
        if not isinstance(now_ms, int) or isinstance(now_ms, bool):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_TIME_INVALID")
        if now_ms < self.valid_from_ms or now_ms >= self.expires_at_ms:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_EXPIRED")


_CREDENTIAL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CREDENTIAL_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


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
    status: CredentialStatus


class ProductionCredentialVault:
    """Audited metadata vault backed by an explicitly selected secret store.

    Production construction requires a persistent backend. Ephemeral credentials
    are available only through :meth:`for_testing`. The event ledger stores
    metadata and fingerprints only; secret bytes are fetched from the backend at
    resolution and are never cached in a vault record.
    """

    REGISTER_EVENT = "PRODUCTION_CREDENTIAL_REGISTERED"
    RESOLVE_EVENT = "PRODUCTION_CREDENTIAL_RESOLVED"
    DENY_EVENT = "PRODUCTION_CREDENTIAL_RESOLUTION_DENIED"
    REVOKE_EVENT = "PRODUCTION_CREDENTIAL_REVOKED"
    _REGISTER_FIELDS = {
        "credential_id", "version", "valid_from_ms", "expires_at_ms", "fingerprint", "status", "actor_role"
    }

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        secret_backend: CredentialSecretBackend | None = None,
        _allow_ephemeral_for_tests: bool = False,
    ):
        if not isinstance(secret_backend, CredentialSecretBackend):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_REQUIRED")
        if not secret_backend.persistent and not _allow_ephemeral_for_tests:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_EPHEMERAL_BACKEND_FORBIDDEN")
        self.__store = store if store is not None else EventStore()
        self.__secret_backend = secret_backend
        self.__records: dict[tuple[str, str], _CredentialRecord] = {}
        self.__lock = RLock()
        self.__restore_metadata()

    @classmethod
    def for_testing(
        cls,
        *,
        store: EventStore | None = None,
        secret_backend: CredentialSecretBackend | None = None,
    ) -> "ProductionCredentialVault":
        """Construct an explicitly ephemeral vault for isolated tests only."""
        return cls(
            store=store,
            secret_backend=secret_backend or InMemoryCredentialSecretBackend(),
            _allow_ephemeral_for_tests=True,
        )

    @property
    def store(self) -> EventStore:
        return self.__store

    @property
    def backend_id(self) -> str:
        return self.__secret_backend.backend_id

    @property
    def backend_persistent(self) -> bool:
        return self.__secret_backend.persistent

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
        role = self._assert_management_access(actor_role)
        if (
            not isinstance(credential_id, str)
            or not isinstance(version, str)
            or not credential_id
            or not version
            or not isinstance(api_key, str)
            or not api_key
            or not isinstance(api_secret, bytes)
            or not api_secret
        ):
            raise ValueError("PRODUCTION_CREDENTIAL_MATERIAL_REQUIRED")
        if (
            not isinstance(valid_from_ms, int)
            or isinstance(valid_from_ms, bool)
            or not isinstance(ttl_ms, int)
            or isinstance(ttl_ms, bool)
            or valid_from_ms < 0
            or ttl_ms <= 0
        ):
            raise ValueError("PRODUCTION_CREDENTIAL_WINDOW_INVALID")
        fingerprint = sha256(api_key.encode("utf-8") + b"|" + api_secret).hexdigest()
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
            "actor_role": role,
        }
        with self.__lock:
            existing = self.__store.get(event_id)
            if existing is not None and (
                existing.event_type != self.REGISTER_EVENT
                or existing.aggregate_id != credential_id
                or dict(existing.payload) != payload
            ):
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_ID_CONFLICT")
            record = self.__records.get(key)
            if record is not None and record.ref != ref:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_ID_CONFLICT")
            if record is not None and record.status is CredentialStatus.REVOKED:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_VERSION_REVOKED")
            try:
                self.__secret_backend.put(
                    credential_id=credential_id,
                    version=version,
                    fingerprint=fingerprint,
                    api_key=api_key,
                    api_secret=api_secret,
                )
            except CredentialBackendError:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_WRITE_FAILED") from None
            if existing is None:
                appended = self.__store.append(
                    event_id=event_id,
                    occurred_at_ms=valid_from_ms,
                    event_type=self.REGISTER_EVENT,
                    aggregate_id=credential_id,
                    payload=payload,
                )
                if dict(appended.event.payload) != payload:
                    raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_ID_CONFLICT")
            self.__records[key] = _CredentialRecord(ref, CredentialStatus.ACTIVE)
            if not self.__store.verify_chain():
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_CHAIN_INVALID")
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
        if not isinstance(ref, ProductionCredentialRef):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID")
        with self.__lock:
            record = self.__records.get((ref.credential_id, ref.version))
            if record is None:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
            if record.ref != ref:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_MISMATCH")
            return ProductionCredentialMetadata(
                record.ref.credential_id,
                record.ref.version,
                record.ref.valid_from_ms,
                record.ref.expires_at_ms,
                record.status,
                record.ref.fingerprint,
            )

    def revoke(self, *, credential_id: str, version: str, now_ms: int, actor_role: str) -> None:
        role = self._assert_authorized(actor_role)
        if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms < 0:
            raise ValueError("PRODUCTION_CREDENTIAL_REVOCATION_TIME_INVALID")
        key = (credential_id, version)
        with self.__lock:
            record = self.__records.get(key)
            if record is None:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
            if record.status is not CredentialStatus.REVOKED:
                payload = {"credential_id": credential_id, "version": version, "actor_role": role}
                appended = self.__store.append(
                    event_id=f"production-credential-revoke:{credential_id}:{version}:{now_ms}",
                    occurred_at_ms=now_ms,
                    event_type=self.REVOKE_EVENT,
                    aggregate_id=credential_id,
                    payload=payload,
                )
                if dict(appended.event.payload) != payload:
                    raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REVOCATION_CONFLICT")
                self.__records[key] = _CredentialRecord(record.ref, CredentialStatus.REVOKED)
                if not self.__store.verify_chain():
                    raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_CHAIN_INVALID")
            try:
                self.__secret_backend.delete(
                    credential_id=credential_id,
                    version=version,
                    fingerprint=record.ref.fingerprint,
                )
            except CredentialBackendError:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_DELETE_FAILED") from None

    def resolve(self, ref: ProductionCredentialRef, *, actor_role: str, now_ms: int) -> RuntimeCredentialValues:
        role = self._normalized_role(actor_role)
        if role != Capability.PRODUCTION_TRADING.value:
            self.__audit_deny(ref, role, now_ms, "ROLE_FORBIDDEN")
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        try:
            assert_capability(role, Capability.PRODUCTION_TRADING)
        except PermissionError:
            self.__audit_deny(ref, role, now_ms, "CAPABILITY_FORBIDDEN")
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        if not isinstance(ref, ProductionCredentialRef):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID")
        ref.validate(now_ms=now_ms)
        with self.__lock:
            record = self.__records.get((ref.credential_id, ref.version))
            if record is None:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_UNKNOWN")
            if record.ref != ref:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_MISMATCH")
            if record.status is not CredentialStatus.ACTIVE:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REVOKED")
            try:
                material = self.__secret_backend.get(
                    credential_id=ref.credential_id,
                    version=ref.version,
                    fingerprint=ref.fingerprint,
                )
            except CredentialBackendError:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_READ_FAILED") from None
            if not isinstance(material, RuntimeCredentialValues):
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_MATERIAL_MISSING")
            api_key, api_secret = material.values()
            observed_fingerprint = sha256(api_key.encode("utf-8") + b"|" + api_secret).hexdigest()
            if observed_fingerprint != ref.fingerprint:
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_BACKEND_INTEGRITY_FAILURE")
            payload = {
                "credential_id": ref.credential_id,
                "version": ref.version,
                "actor_role": role,
                "fingerprint": ref.fingerprint,
            }
            appended = self.__store.append(
                event_id=f"production-credential-resolve:{ref.credential_id}:{ref.version}:{now_ms}:{uuid4().hex}",
                occurred_at_ms=now_ms,
                event_type=self.RESOLVE_EVENT,
                aggregate_id=ref.credential_id,
                payload=payload,
            )
            if dict(appended.event.payload) != payload or not self.__store.verify_chain():
                raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_CHAIN_INVALID")
            return material

    @staticmethod
    def _normalized_role(actor_role: Any) -> str:
        if not isinstance(actor_role, str):
            return "UNKNOWN"
        role = actor_role.upper()
        allowed = {capability.value for capability in Capability}
        return role if role in allowed else "UNKNOWN"

    def _assert_management_access(self, actor_role: str) -> str:
        role = self._normalized_role(actor_role)
        if role not in {Capability.SECURITY_ADMIN.value, Capability.PRODUCTION_TRADING.value}:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        assert_capability(role, Capability.CONFIGURATION)
        return role

    def _assert_authorized(self, actor_role: str) -> str:
        role = self._normalized_role(actor_role)
        if role != Capability.PRODUCTION_TRADING.value:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_RESEARCH_FORBIDDEN")
        assert_capability(role, Capability.PRODUCTION_TRADING)
        return role

    def __audit_deny(self, ref: ProductionCredentialRef, actor_role: str, now_ms: int, reason: str) -> None:
        safe_role = self._normalized_role(actor_role)
        if not isinstance(ref, ProductionCredentialRef):
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID")
        try:
            ref.validate(now_ms=now_ms)
        except ProductionCredentialAccessError:
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_REFERENCE_INVALID") from None
        self.__store.append(
            event_id=f"production-credential-deny:{ref.credential_id}:{ref.version}:{now_ms}:{safe_role}:{reason}:{uuid4().hex}",
            occurred_at_ms=now_ms,
            event_type=self.DENY_EVENT,
            aggregate_id=ref.credential_id,
            payload={
                "credential_id": ref.credential_id,
                "version": ref.version,
                "actor_role": safe_role,
                "reason": reason,
            },
        )
        if not self.__store.verify_chain():
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_CHAIN_INVALID")

    def __restore_metadata(self) -> None:
        if not self.__store.verify_chain():
            raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_CHAIN_INVALID")
        records: dict[tuple[str, str], _CredentialRecord] = {}
        legacy_register_fields = self._REGISTER_FIELDS - {"actor_role"}
        for event in self.__store.iter_events():
            payload = event.payload
            if event.event_type == self.REGISTER_EVENT:
                try:
                    fields = frozenset(payload)
                    if fields not in {frozenset(self._REGISTER_FIELDS), frozenset(legacy_register_fields)}:
                        raise ValueError
                    credential_id = payload["credential_id"]
                    version = payload["version"]
                    if event.aggregate_id != credential_id:
                        raise ValueError
                    role = payload.get("actor_role", "UNKNOWN")
                    if role != "UNKNOWN" and role not in {
                        Capability.SECURITY_ADMIN.value,
                        Capability.PRODUCTION_TRADING.value,
                    }:
                        raise ValueError
                    status = CredentialStatus(payload["status"])
                    if status is not CredentialStatus.ACTIVE:
                        raise ValueError
                    ref = ProductionCredentialRef(
                        credential_id=credential_id,
                        version=version,
                        valid_from_ms=payload["valid_from_ms"],
                        expires_at_ms=payload["expires_at_ms"],
                        fingerprint=payload["fingerprint"],
                    )
                    ref.validate(now_ms=ref.valid_from_ms)
                    key = (credential_id, version)
                    prior = records.get(key)
                    restored = _CredentialRecord(ref, CredentialStatus.ACTIVE)
                    if prior is not None and prior.ref != ref:
                        raise ValueError
                    records[key] = restored
                except (KeyError, TypeError, ValueError, ProductionCredentialAccessError):
                    raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_SCHEMA_INVALID") from None
            elif event.event_type == self.REVOKE_EVENT:
                try:
                    if set(payload) != {"credential_id", "version", "actor_role"}:
                        raise ValueError
                    credential_id = payload["credential_id"]
                    version = payload["version"]
                    role = payload["actor_role"]
                    if event.aggregate_id != credential_id or role != Capability.PRODUCTION_TRADING.value:
                        raise ValueError
                    key = (credential_id, version)
                    prior = records[key]
                    records[key] = _CredentialRecord(prior.ref, CredentialStatus.REVOKED)
                except (KeyError, TypeError, ValueError):
                    raise ProductionCredentialAccessError("PRODUCTION_CREDENTIAL_AUDIT_SCHEMA_INVALID") from None
        self.__records = records


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
    normalized = key.lower().replace("-", "_")
    candidates = (
        normalized.strip("_"),
        normalized.rsplit("__", 1)[-1].strip("_"),
    )
    return any(candidate in _CREDENTIAL_KEY_MARKERS for candidate in candidates)


def _iter_research_slots(value: Any):
    """Yield declared slot names and their Python-mangled attribute names."""
    for owner in type(value).__mro__:
        declared = owner.__dict__.get("__slots__", ())
        if isinstance(declared, str):
            declared = (declared,)
        for name in declared:
            if not isinstance(name, str) or name in {"__dict__", "__weakref__"}:
                continue
            attribute = name
            if name.startswith("__") and not name.endswith("__"):
                attribute = f"_{owner.__name__.lstrip('_')}{name}"
            yield name, attribute


def assert_research_safe(value: Any, *, _seen: set[int] | None = None) -> None:
    """Fail closed if production credential material or handles cross research boundaries."""
    seen = _seen or set()
    ident = id(value)
    if ident in seen:
        return
    seen.add(ident)
    if isinstance(value, (RuntimeCredentialValues, ProductionCredentialRef, ProductionCredentialMetadata, ProductionCredentialVault, CredentialSecretBackend, _CredentialRecord)):
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
    # NumPy object arrays can carry credential objects inside model inputs; numeric
    # arrays contain no Python object references and need no element traversal.
    if any(
        base.__module__.startswith("numpy") and "ndarray" in base.__name__
        for base in type(value).__mro__
    ):
        try:
            dtype = object.__getattribute__(value, "dtype")
        except AttributeError:
            dtype = None
        if dtype is not None and getattr(dtype, "hasobject", False):
            names = getattr(dtype, "names", None)
            for item in object.__getattribute__(value, "flat"):
                if names:
                    for field_name in names:
                        assert_research_safe(item[field_name], _seen=seen)
                else:
                    assert_research_safe(item, _seen=seen)
            return
    if hasattr(value, "__dict__"):
        for k, v in vars(value).items():
            if _looks_like_credential_key(k):
                raise ProductionCredentialAccessError("RESEARCH_PRODUCTION_CREDENTIAL_VISIBILITY_FORBIDDEN")
            assert_research_safe(v, _seen=seen)
    for name, attribute in _iter_research_slots(value):
        if _looks_like_credential_key(name) or _looks_like_credential_key(attribute):
            raise ProductionCredentialAccessError("RESEARCH_PRODUCTION_CREDENTIAL_VISIBILITY_FORBIDDEN")
        try:
            slot_value = object.__getattribute__(value, attribute)
        except AttributeError:
            continue
        assert_research_safe(slot_value, _seen=seen)


def assert_research_arguments(*args: Any, **kwargs: Any) -> None:
    for arg in args:
        assert_research_safe(arg)
    assert_research_safe(kwargs)

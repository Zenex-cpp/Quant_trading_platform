"""V3.89 runtime Testnet credential capability boundary.

The first Testnet mutation must not accept an undifferentiated credential blob.
V3.89 binds runtime credential use to TESTNET scope, a dedicated environment
source, a bounded validity window, the exact allowed endpoint host and a one-shot
capability. The capability exposes no secret material through repr/metadata and
cannot be consumed twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import os
from typing import Mapping
from urllib.parse import urlparse

from trading_platform.v35.binance_execution import RuntimeCredentialValues


class TestnetCredentialErrorV389(PermissionError):
    """Raised when a Testnet runtime credential capability is unsafe."""
    __test__ = False


class CredentialScopeV389(str, Enum):
    TESTNET = "TESTNET"


class CredentialSourceV389(str, Enum):
    ENVIRONMENT = "ENVIRONMENT"


@dataclass(frozen=True)
class TestnetCredentialRefV389:
    credential_id: str
    version: str
    scope: CredentialScopeV389
    source: CredentialSourceV389
    valid_from: datetime
    expires_at: datetime
    key_fingerprint: str

    def validate(self, *, now: datetime) -> None:
        if self.scope is not CredentialScopeV389.TESTNET:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_SCOPE_INVALID")
        if self.source is not CredentialSourceV389.ENVIRONMENT:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_SOURCE_INVALID")
        if not self.credential_id or not self.version or not self.key_fingerprint:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_REFERENCE_INVALID")
        if self.expires_at <= self.valid_from:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_WINDOW_INVALID")
        if now < self.valid_from or now >= self.expires_at:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_EXPIRED")
        if len(self.key_fingerprint) != 64:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_FINGERPRINT_INVALID")


@dataclass(frozen=True)
class TestnetCredentialCapabilityMetadataV389:
    capability_id: str
    credential_id: str
    version: str
    scope: CredentialScopeV389
    source: CredentialSourceV389
    issued_at: datetime
    expires_at: datetime
    endpoint_host: str
    key_fingerprint: str

    def safe_payload(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "credential_id": self.credential_id,
            "version": self.version,
            "scope": self.scope.value,
            "source": self.source.value,
            "issued_at": self.issued_at.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "endpoint_host": self.endpoint_host,
            "key_fingerprint": self.key_fingerprint,
        }


class TestnetRuntimeCredentialCapabilityV389:
    """One-shot capability that releases runtime credentials exactly once."""

    __test__ = False

    def __init__(
        self,
        *,
        metadata: TestnetCredentialCapabilityMetadataV389,
        ref: TestnetCredentialRefV389,
        credentials: RuntimeCredentialValues,
    ) -> None:
        self._metadata = metadata
        self._ref = ref
        self._credentials = credentials
        self._consumed = False

    @property
    def capability_id(self) -> str:
        return self._metadata.capability_id

    @property
    def consumed(self) -> bool:
        return self._consumed

    @property
    def metadata(self) -> TestnetCredentialCapabilityMetadataV389:
        return self._metadata

    def __repr__(self) -> str:
        return (
            "TestnetRuntimeCredentialCapabilityV389("
            f"capability_id={self.capability_id!r}, scope={self._metadata.scope.value!r}, "
            f"endpoint_host={self._metadata.endpoint_host!r}, consumed={self._consumed!r})"
        )

    def assert_valid(self, *, now: datetime, endpoint: str) -> None:
        self._ref.validate(now=now)
        _validate_endpoint(endpoint)
        host = urlparse(endpoint).hostname or ""
        if host.lower() != self._metadata.endpoint_host:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_ENDPOINT_MISMATCH")
        if self._consumed:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_CAPABILITY_CONSUMED")

    def consume(self, *, now: datetime, endpoint: str) -> RuntimeCredentialValues:
        self.assert_valid(now=now, endpoint=endpoint)
        self._consumed = True
        return self._credentials


class TestnetRuntimeCredentialAuthorityV389:
    """Acquires Testnet credentials from dedicated environment variables only."""

    API_KEY_ENV = "BINANCE_TESTNET_API_KEY"
    API_SECRET_ENV = "BINANCE_TESTNET_API_SECRET"
    FORBIDDEN_PRODUCTION_ENV = (
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_PROD_API_KEY",
        "BINANCE_PROD_API_SECRET",
    )
    DEFAULT_ENDPOINT_HOST = "testnet.binancefuture.com"

    @classmethod
    def issue_from_environment(
        cls,
        *,
        now: datetime,
        ttl_s: int = 300,
        endpoint: str = "https://testnet.binancefuture.com",
        credential_id: str = "binance-testnet-runtime",
        version: str = "env-v1",
        environ: Mapping[str, str] | None = None,
    ) -> TestnetRuntimeCredentialCapabilityV389:
        _validate_endpoint(endpoint)
        if ttl_s <= 0:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_TTL_INVALID")
        if now.tzinfo is None:
            raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_TIMEZONE_REQUIRED")
        env = environ if environ is not None else os.environ
        for name in cls.FORBIDDEN_PRODUCTION_ENV:
            if env.get(name):
                raise TestnetCredentialErrorV389("PRODUCTION_CREDENTIAL_PRESENCE_BLOCKED")
        api_key = env.get(cls.API_KEY_ENV, "")
        api_secret = env.get(cls.API_SECRET_ENV, "")
        if not api_key or not api_secret:
            raise TestnetCredentialErrorV389("TESTNET_RUNTIME_CREDENTIALS_MISSING")
        if any(ch.isspace() for ch in api_key) or any(ch.isspace() for ch in api_secret):
            raise TestnetCredentialErrorV389("TESTNET_RUNTIME_CREDENTIAL_FORMAT_INVALID")
        host = (urlparse(endpoint).hostname or "").lower()
        key_fingerprint = sha256(api_key.encode("utf-8") + b"|" + api_secret.encode("utf-8")).hexdigest()
        expires_at = now.astimezone(timezone.utc).replace(microsecond=0)
        expires_at = expires_at.fromtimestamp(expires_at.timestamp() + ttl_s, tz=timezone.utc)
        ref = TestnetCredentialRefV389(
            credential_id=credential_id,
            version=version,
            scope=CredentialScopeV389.TESTNET,
            source=CredentialSourceV389.ENVIRONMENT,
            valid_from=now,
            expires_at=expires_at,
            key_fingerprint=key_fingerprint,
        )
        capability_id = sha256(
            f"{credential_id}|{version}|TESTNET|ENVIRONMENT|{host}|{key_fingerprint}|{now.astimezone(timezone.utc).isoformat()}".encode()
        ).hexdigest()
        metadata = TestnetCredentialCapabilityMetadataV389(
            capability_id=capability_id,
            credential_id=credential_id,
            version=version,
            scope=CredentialScopeV389.TESTNET,
            source=CredentialSourceV389.ENVIRONMENT,
            issued_at=now,
            expires_at=expires_at,
            endpoint_host=host,
            key_fingerprint=key_fingerprint,
        )
        return TestnetRuntimeCredentialCapabilityV389(
            metadata=metadata,
            ref=ref,
            credentials=RuntimeCredentialValues(api_key, api_secret.encode("utf-8")),
        )


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_ENDPOINT_TLS_REQUIRED")
    host = (parsed.hostname or "").lower()
    if host != TestnetRuntimeCredentialAuthorityV389.DEFAULT_ENDPOINT_HOST:
        raise TestnetCredentialErrorV389("TESTNET_CREDENTIAL_ENDPOINT_NOT_ALLOWED")

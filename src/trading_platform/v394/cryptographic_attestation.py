"""V3.94 cryptographic attestation verification.

Verifies Ed25519 signatures over a canonical binding of the exact evidence package
and accepted independent-review attestation from V3.93. The trust-anchor registry
is versioned and fail-closed for unknown, expired, revoked, scope-incompatible or
otherwise invalid keys. This is cryptographic verification in-process; it does not
claim that the configured trust-anchor registry itself has been externally attested.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import base64
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import canonical_json
from trading_platform.v393.external_review_authority import ExternalReviewAttestationV393


class CryptographicAttestationErrorV394(ValueError):
    __test__ = False


class SignatureAlgorithmV394(str, Enum):
    ED25519 = "ED25519"


class KeyStatusV394(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class CryptoVerificationStateV394(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class TrustAnchorAttestationStateV394(str, Enum):
    ATTESTED = "ATTESTED"
    UNATTESTED = "UNATTESTED"


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return canonical_json(value)


def _b64decode(value: str, *, field: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise CryptographicAttestationErrorV394(f"{field}_BASE64_INVALID") from exc
    if not raw:
        raise CryptographicAttestationErrorV394(f"{field}_EMPTY")
    return raw


@dataclass(frozen=True)
class TrustAnchorV394:
    key_id: str
    algorithm: SignatureAlgorithmV394
    public_key_b64: str
    valid_from_ms: int
    expires_at_ms: int
    status: KeyStatusV394
    allowed_scopes: tuple[str, ...]
    registry_version: str
    key_fingerprint: str

    def public_key_bytes(self) -> bytes:
        raw = _b64decode(self.public_key_b64, field="PUBLIC_KEY")
        if self.algorithm is not SignatureAlgorithmV394.ED25519:
            raise CryptographicAttestationErrorV394("SIGNATURE_ALGORITHM_UNSUPPORTED")
        if len(raw) != 32:
            raise CryptographicAttestationErrorV394("ED25519_PUBLIC_KEY_LENGTH_INVALID")
        return raw

    def computed_fingerprint(self) -> str:
        return _sha256_bytes(self.public_key_bytes())

    def validate(self, *, scope: str, now_ms: int) -> None:
        if not self.key_id or not self.registry_version:
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_IDENTIFIERS_REQUIRED")
        if not self.allowed_scopes or scope not in set(self.allowed_scopes):
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_SCOPE_NOT_ALLOWED")
        if self.valid_from_ms < 0 or self.expires_at_ms <= self.valid_from_ms:
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_VALIDITY_INVALID")
        if not (self.valid_from_ms <= now_ms < self.expires_at_ms):
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_EXPIRED")
        if self.status is not KeyStatusV394.ACTIVE:
            raise CryptographicAttestationErrorV394(f"TRUST_ANCHOR_{self.status.value}")
        if self.key_fingerprint != self.computed_fingerprint():
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_FINGERPRINT_MISMATCH")
        self.public_key_bytes()

    def safe_payload(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "algorithm": self.algorithm.value,
            "public_key_fingerprint": self.key_fingerprint,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
            "status": self.status.value,
            "allowed_scopes": list(self.allowed_scopes),
            "registry_version": self.registry_version,
        }


@dataclass(frozen=True)
class SignedReviewEnvelopeV394:
    envelope_id: str
    package_id: str
    package_hash: str
    review_id: str
    review_hash: str
    scope: str
    key_id: str
    algorithm: SignatureAlgorithmV394
    signature_b64: str
    signature_hash: str
    trust_registry_version: str
    trust_anchor_attestation: TrustAnchorAttestationStateV394

    def signing_body(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_hash": self.package_hash,
            "review_id": self.review_id,
            "review_hash": self.review_hash,
            "scope": self.scope,
        }

    def signing_bytes(self) -> bytes:
        return _canonical(self.signing_body())

    def signature_bytes(self) -> bytes:
        return _b64decode(self.signature_b64, field="SIGNATURE")

    def computed_signature_hash(self) -> str:
        return _sha256_bytes(self.signature_bytes())

    def validate_structure(self) -> None:
        if not self.envelope_id or not self.package_id or not self.package_hash or not self.review_id or not self.review_hash:
            raise CryptographicAttestationErrorV394("SIGNED_REVIEW_IDENTIFIERS_REQUIRED")
        if self.algorithm is not SignatureAlgorithmV394.ED25519:
            raise CryptographicAttestationErrorV394("SIGNATURE_ALGORITHM_UNSUPPORTED")
        if self.computed_signature_hash() != self.signature_hash:
            raise CryptographicAttestationErrorV394("SIGNATURE_HASH_MISMATCH")
        if self.trust_anchor_attestation is not TrustAnchorAttestationStateV394.ATTESTED:
            raise CryptographicAttestationErrorV394("TRUST_ANCHOR_ATTESTATION_REQUIRED")

    def safe_payload(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "package_id": self.package_id,
            "package_hash": self.package_hash,
            "review_id": self.review_id,
            "review_hash": self.review_hash,
            "scope": self.scope,
            "key_id": self.key_id,
            "algorithm": self.algorithm.value,
            "signature_hash": self.signature_hash,
            "trust_registry_version": self.trust_registry_version,
            "trust_anchor_attestation": self.trust_anchor_attestation.value,
        }


@dataclass(frozen=True)
class CryptographicAttestationDecisionV394:
    allowed: bool
    reason: str
    package_id: str
    review_id: str
    key_id: str
    verification: CryptoVerificationStateV394
    evidence_status: str
    envelope_id: str | None

    def safe_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "package_id": self.package_id,
            "review_id": self.review_id,
            "key_id": self.key_id,
            "verification": self.verification.value,
            "evidence_status": self.evidence_status,
            "envelope_id": self.envelope_id,
        }


class CryptographicAttestationAuthorityV394:
    EVENT_TYPE = "CRYPTOGRAPHIC_REVIEW_ATTESTATION_VERIFIED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def verify(
        self,
        *,
        package: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        envelope: SignedReviewEnvelopeV394,
        trust_anchor: TrustAnchorV394,
        now_ms: int,
    ) -> CryptographicAttestationDecisionV394:
        try:
            envelope.validate_structure()
            if envelope.package_id != str(package.get("package_id")) or envelope.review_id != review.review_id:
                raise CryptographicAttestationErrorV394("SIGNED_SUBJECT_MISMATCH")
            if envelope.package_hash != str(package.get("package_hash")) or envelope.review_hash != review.review_hash:
                raise CryptographicAttestationErrorV394("SIGNED_HASH_BINDING_MISMATCH")
            if envelope.scope != review.scope:
                raise CryptographicAttestationErrorV394("SIGNED_SCOPE_MISMATCH")
            if envelope.key_id != trust_anchor.key_id or envelope.trust_registry_version != trust_anchor.registry_version:
                raise CryptographicAttestationErrorV394("TRUST_ANCHOR_REFERENCE_MISMATCH")
            trust_anchor.validate(scope=review.scope, now_ms=now_ms)
            public_key = Ed25519PublicKey.from_public_bytes(trust_anchor.public_key_bytes())
            try:
                public_key.verify(envelope.signature_bytes(), envelope.signing_bytes())
            except InvalidSignature as exc:
                raise CryptographicAttestationErrorV394("SIGNATURE_INVALID") from exc

            event_id = f"crypto-review:{envelope.envelope_id}:verified"
            payload = {
                **envelope.safe_payload(),
                "reviewer_id": review.reviewer_id,
                "verified_at_ms": now_ms,
                "verification": CryptoVerificationStateV394.VERIFIED.value,
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(
                    event_id=event_id,
                    occurred_at_ms=now_ms,
                    event_type=self.EVENT_TYPE,
                    aggregate_id=envelope.review_id,
                    payload=payload,
                )
            else:
                comparable_existing = dict(existing.payload)
                comparable_payload = dict(payload)
                comparable_existing.pop("verified_at_ms", None)
                comparable_payload.pop("verified_at_ms", None)
                if comparable_existing != comparable_payload:
                    raise CryptographicAttestationErrorV394("CRYPTO_REVIEW_DUPLICATE_CONFLICT")
                payload = dict(existing.payload)
            return CryptographicAttestationDecisionV394(
                True,
                "CRYPTOGRAPHIC_SIGNATURE_VERIFIED",
                envelope.package_id,
                envelope.review_id,
                envelope.key_id,
                CryptoVerificationStateV394.VERIFIED,
                "CRYPTOGRAPHICALLY_VERIFIED_IN_PROCESS_TRUST_ANCHOR_ATTESTED",
                envelope.envelope_id,
            )
        except CryptographicAttestationErrorV394 as exc:
            return CryptographicAttestationDecisionV394(
                False,
                str(exc),
                envelope.package_id,
                envelope.review_id,
                envelope.key_id,
                CryptoVerificationStateV394.REJECTED,
                "NOT_VERIFIED",
                envelope.envelope_id,
            )

    def get(self, envelope_id: str):
        return self.store.get(f"crypto-review:{envelope_id}:verified")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

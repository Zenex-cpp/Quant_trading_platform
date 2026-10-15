"""V3.95 external trust-anchor attestation intake.

This module does not manufacture custody, ceremony or HSM evidence. It accepts an
externally produced attestation only when the supplied proof set exactly matches
the runtime trust-registry snapshot and a separately trusted reviewer signature.
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
from trading_platform.v394.cryptographic_attestation import KeyStatusV394, TrustAnchorV394


class TrustAttestationErrorV395(ValueError):
    __test__ = False


class AttestationStatusV395(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    NOT_VERIFIED = "NOT_VERIFIED"


class ReviewerKeyStatusV395(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


def _sha256_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return canonical_json(value)


def _b64decode(value: str, *, field: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise TrustAttestationErrorV395(f"{field}_BASE64_INVALID") from exc
    if not raw:
        raise TrustAttestationErrorV395(f"{field}_EMPTY")
    return raw


def _reject_sensitive(value: Any, path: str = "root") -> None:
    forbidden = {"secret", "secrets", "private_key", "api_key", "api_secret", "password", "token", "credential", "credentials"}
    if isinstance(value, Mapping):
        for key, nested in value.items():
            k = str(key).lower()
            if k in forbidden or any(fragment in k for fragment in ("private_key", "api_secret", "password")):
                raise TrustAttestationErrorV395(f"SENSITIVE_ATTESTATION_FIELD:{path}.{key}")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{i}]")


@dataclass(frozen=True)
class TrustRegistrySnapshotV395:
    registry_version: str
    anchors: tuple[TrustAnchorV394, ...]
    registry_hash: str

    def body(self) -> dict[str, Any]:
        ordered = sorted((a.safe_payload() for a in self.anchors), key=lambda x: (x["key_id"], x["public_key_fingerprint"]))
        return {"registry_version": self.registry_version, "anchors": ordered}

    def computed_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body()))

    def validate(self) -> None:
        if not self.registry_version or not self.anchors:
            raise TrustAttestationErrorV395("REGISTRY_SNAPSHOT_INCOMPLETE")
        if any(a.registry_version != self.registry_version for a in self.anchors):
            raise TrustAttestationErrorV395("REGISTRY_VERSION_MISMATCH")
        if len({a.key_id for a in self.anchors}) != len(self.anchors):
            raise TrustAttestationErrorV395("REGISTRY_DUPLICATE_KEY_ID")
        if self.registry_hash != self.computed_hash():
            raise TrustAttestationErrorV395("REGISTRY_HASH_MISMATCH")

    @property
    def fingerprint_set(self) -> tuple[str, ...]:
        return tuple(sorted(a.key_fingerprint for a in self.anchors))


@dataclass(frozen=True)
class ReviewerTrustAnchorV395:
    reviewer_key_id: str
    public_key_b64: str
    valid_from_ms: int
    expires_at_ms: int
    status: ReviewerKeyStatusV395
    allowed_scopes: tuple[str, ...]
    fingerprint: str

    def public_key_bytes(self) -> bytes:
        raw = _b64decode(self.public_key_b64, field="REVIEWER_PUBLIC_KEY")
        if len(raw) != 32:
            raise TrustAttestationErrorV395("REVIEWER_PUBLIC_KEY_LENGTH_INVALID")
        return raw

    def computed_fingerprint(self) -> str:
        return _sha256_bytes(self.public_key_bytes())

    def validate(self, *, scope: str, now_ms: int) -> None:
        if not self.reviewer_key_id or not self.allowed_scopes or scope not in set(self.allowed_scopes):
            raise TrustAttestationErrorV395("REVIEWER_SCOPE_NOT_ALLOWED")
        if self.status is not ReviewerKeyStatusV395.ACTIVE:
            raise TrustAttestationErrorV395(f"REVIEWER_KEY_{self.status.value}")
        if not (self.valid_from_ms <= now_ms < self.expires_at_ms):
            raise TrustAttestationErrorV395("REVIEWER_KEY_EXPIRED")
        if self.fingerprint != self.computed_fingerprint():
            raise TrustAttestationErrorV395("REVIEWER_FINGERPRINT_MISMATCH")
        self.public_key_bytes()


@dataclass(frozen=True)
class RevocationDrillEvidenceV395:
    drill_id: str
    target_key_id: str
    executed_at_ms: int
    passed: bool
    revoked_anchor_blocked: bool
    evidence_ref: str

    def validate(self, *, now_ms: int) -> None:
        if not self.drill_id or not self.target_key_id or not self.evidence_ref:
            raise TrustAttestationErrorV395("REVOCATION_DRILL_INCOMPLETE")
        if self.evidence_ref.startswith(("demo:", "synthetic:")):
            raise TrustAttestationErrorV395("SYNTHETIC_REVOCATION_EVIDENCE_FORBIDDEN")
        if self.executed_at_ms < 0 or self.executed_at_ms > now_ms:
            raise TrustAttestationErrorV395("REVOCATION_DRILL_TIME_INVALID")
        if not (self.passed and self.revoked_anchor_blocked):
            raise TrustAttestationErrorV395("REVOCATION_DRILL_NOT_PROVEN")


@dataclass(frozen=True)
class ExternalTrustAnchorAttestationV395:
    attestation_id: str
    scope: str
    registry_version: str
    registry_hash: str
    anchor_fingerprints: tuple[str, ...]
    custodian_id: str
    custody_evidence_ref: str
    ceremony_evidence_ref: str
    revocation_drill: RevocationDrillEvidenceV395
    reviewer_id: str
    reviewer_key_id: str
    reviewed_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "scope": self.scope,
            "registry_version": self.registry_version,
            "registry_hash": self.registry_hash,
            "anchor_fingerprints": sorted(self.anchor_fingerprints),
            "custodian_id": self.custodian_id,
            "custody_evidence_ref": self.custody_evidence_ref,
            "ceremony_evidence_ref": self.ceremony_evidence_ref,
            "revocation_drill_id": self.revocation_drill.drill_id,
            "revocation_target_key_id": self.revocation_drill.target_key_id,
            "revocation_evidence_ref": self.revocation_drill.evidence_ref,
            "reviewer_id": self.reviewer_id,
            "reviewer_key_id": self.reviewer_key_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def computed_attestation_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body_for_hash()))

    def signature_bytes(self) -> bytes:
        return _b64decode(self.signature_b64, field="ATTESTATION_SIGNATURE")

    def validate_structure(self, *, now_ms: int, max_ttl_ms: int = 7 * 24 * 3600 * 1000) -> None:
        _reject_sensitive(self.body_for_hash())
        required = (self.attestation_id, self.scope, self.registry_version, self.registry_hash, self.custodian_id, self.custody_evidence_ref, self.ceremony_evidence_ref, self.reviewer_id, self.reviewer_key_id, self.signature_hash)
        if any(not str(v) for v in required):
            raise TrustAttestationErrorV395("ATTESTATION_IDENTIFIERS_REQUIRED")
        if self.decision != "ACCEPT":
            raise TrustAttestationErrorV395("ATTESTATION_DECISION_NOT_ACCEPT")
        if len(set(self.anchor_fingerprints)) != len(self.anchor_fingerprints) or not self.anchor_fingerprints:
            raise TrustAttestationErrorV395("ATTESTATION_FINGERPRINT_SET_INVALID")
        for ref_name, ref in (("CUSTODY", self.custody_evidence_ref), ("CEREMONY", self.ceremony_evidence_ref)):
            if ref.startswith(("demo:", "synthetic:")):
                raise TrustAttestationErrorV395(f"SYNTHETIC_{ref_name}_EVIDENCE_FORBIDDEN")
        if self.reviewer_id == self.custodian_id:
            raise TrustAttestationErrorV395("REVIEWER_CUSTODIAN_CONFLICT")
        if not (self.reviewed_at_ms < self.expires_at_ms and self.expires_at_ms - self.reviewed_at_ms <= max_ttl_ms):
            raise TrustAttestationErrorV395("ATTESTATION_VALIDITY_INVALID")
        if not (self.reviewed_at_ms <= now_ms < self.expires_at_ms):
            raise TrustAttestationErrorV395("ATTESTATION_EXPIRED")
        if _sha256_bytes(self.signature_bytes()) != self.signature_hash:
            raise TrustAttestationErrorV395("ATTESTATION_SIGNATURE_HASH_MISMATCH")

    def safe_payload(self) -> dict[str, Any]:
        return {**self.body_for_hash(), "signature_hash": self.signature_hash, "fingerprint": _sha256_bytes(_canonical({"attestation_id": self.attestation_id, "registry_hash": self.registry_hash}))}


@dataclass(frozen=True)
class TrustAnchorAttestationDecisionV395:
    allowed: bool
    reason: str
    attestation_id: str
    registry_version: str
    registry_hash: str
    status: AttestationStatusV395
    reviewer_id: str | None


class TrustAnchorAttestationAuthorityV395:
    EVENT_TYPE = "TRUST_ANCHOR_ATTESTATION_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def intake(
        self,
        *,
        snapshot: TrustRegistrySnapshotV395,
        attestation: ExternalTrustAnchorAttestationV395,
        reviewer_anchor: ReviewerTrustAnchorV395,
        now_ms: int,
    ) -> TrustAnchorAttestationDecisionV395:
        try:
            snapshot.validate()
            attestation.validate_structure(now_ms=now_ms)
            attestation.revocation_drill.validate(now_ms=now_ms)
            if snapshot.registry_version != attestation.registry_version or snapshot.registry_hash != attestation.registry_hash:
                raise TrustAttestationErrorV395("ATTESTATION_REGISTRY_BINDING_MISMATCH")
            if tuple(sorted(attestation.anchor_fingerprints)) != snapshot.fingerprint_set:
                raise TrustAttestationErrorV395("ATTESTATION_FINGERPRINT_SET_MISMATCH")
            if attestation.reviewer_key_id != reviewer_anchor.reviewer_key_id:
                raise TrustAttestationErrorV395("REVIEWER_KEY_REFERENCE_MISMATCH")
            reviewer_anchor.validate(scope=attestation.scope, now_ms=now_ms)
            try:
                Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(attestation.signature_bytes(), _canonical(attestation.body_for_hash()))
            except InvalidSignature as exc:
                raise TrustAttestationErrorV395("ATTESTATION_SIGNATURE_INVALID") from exc
            event_id = f"trust-anchor-attestation:{attestation.attestation_id}:accepted"
            payload = {**attestation.safe_payload(), "reviewer_key_fingerprint": reviewer_anchor.fingerprint, "status": AttestationStatusV395.VERIFIED.value}
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(event_id=event_id, occurred_at_ms=now_ms, event_type=self.EVENT_TYPE, aggregate_id=attestation.attestation_id, payload=payload)
            elif dict(existing.payload) != payload:
                raise TrustAttestationErrorV395("ATTESTATION_EVENT_ID_CONFLICT")
            return TrustAnchorAttestationDecisionV395(True, "EXTERNAL_TRUST_ANCHOR_ATTESTATION_ACCEPTED", attestation.attestation_id, snapshot.registry_version, snapshot.registry_hash, AttestationStatusV395.VERIFIED, attestation.reviewer_id)
        except TrustAttestationErrorV395 as exc:
            status = AttestationStatusV395.EXPIRED if "EXPIRED" in str(exc) else AttestationStatusV395.REJECTED
            return TrustAnchorAttestationDecisionV395(False, str(exc), attestation.attestation_id, attestation.registry_version, attestation.registry_hash, status, attestation.reviewer_id)

    def get(self, attestation_id: str):
        return self.store.get(f"trust-anchor-attestation:{attestation_id}:accepted")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

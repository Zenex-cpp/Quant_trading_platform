from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v395.trust_anchor_attestation import ReviewerTrustAnchorV395, TrustAttestationErrorV395


class RevocationErrorV404(ValueError):
    __test__ = False


class RevalidationStatusV404(str, Enum):
    REVALIDATED = "REVALIDATED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _reject_sensitive(value: Any, path: str = "root") -> None:
    forbidden = {"secret", "secrets", "private_key", "api_key", "api_secret", "password", "token", "credential", "credentials"}
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in forbidden or any(fragment in lowered for fragment in ("private_key", "api_secret", "password")):
                raise RevocationErrorV404(f"SENSITIVE_REVOCATION_FIELD:{path}.{key}")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{idx}]")


@dataclass(frozen=True)
class ReadinessRevocationV404:
    revocation_id: str
    scope: str
    witness_id: str
    witness_fingerprint: str
    bundle_id: str
    evidence_snapshot_id: str
    release_artifact_hash: str
    reason_code: str
    reviewer_id: str
    operator_id: str
    reviewer_key_id: str
    revoked_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "REVOKE"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "revocation_id": self.revocation_id,
            "scope": self.scope,
            "witness_id": self.witness_id,
            "witness_fingerprint": self.witness_fingerprint,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "release_artifact_hash": self.release_artifact_hash,
            "reason_code": self.reason_code,
            "reviewer_id": self.reviewer_id,
            "operator_id": self.operator_id,
            "reviewer_key_id": self.reviewer_key_id,
            "revoked_at_ms": self.revoked_at_ms,
            "decision": self.decision,
        }

    def fingerprint(self) -> str:
        return _sha(_canonical(self.body_for_hash()))

    def signature_bytes(self) -> bytes:
        try:
            raw = b64decode(self.signature_b64.encode("ascii"), validate=True)
        except Exception as exc:
            raise RevocationErrorV404("REVOCATION_SIGNATURE_BASE64_INVALID") from exc
        if not raw:
            raise RevocationErrorV404("REVOCATION_SIGNATURE_EMPTY")
        return raw

    def validate(self, *, now_ms: int, reviewer_anchor: ReviewerTrustAnchorV395) -> None:
        _reject_sensitive(self.body_for_hash())
        required = (
            self.revocation_id,
            self.scope,
            self.witness_id,
            self.witness_fingerprint,
            self.bundle_id,
            self.evidence_snapshot_id,
            self.release_artifact_hash,
            self.reason_code,
            self.reviewer_id,
            self.operator_id,
            self.reviewer_key_id,
            self.signature_hash,
        )
        if any(not str(value) for value in required):
            raise RevocationErrorV404("REVOCATION_REQUIRED_FIELD_MISSING")
        if self.decision != "REVOKE":
            raise RevocationErrorV404("REVOCATION_DECISION_INVALID")
        if self.scope != "PRODUCTION_CRITICAL":
            raise RevocationErrorV404("REVOCATION_SCOPE_INVALID")
        if self.reviewer_id == self.operator_id:
            raise RevocationErrorV404("REVOCATION_REVIEWER_OPERATOR_CONFLICT")
        if self.revoked_at_ms < 0 or self.revoked_at_ms > now_ms:
            raise RevocationErrorV404("REVOCATION_TIMESTAMP_INVALID")
        if len(self.witness_fingerprint) != 64 or len(self.release_artifact_hash) != 64:
            raise RevocationErrorV404("REVOCATION_HASH_INVALID")
        if self.reviewer_key_id != reviewer_anchor.reviewer_key_id:
            raise RevocationErrorV404("REVOCATION_REVIEWER_KEY_MISMATCH")
        reviewer_anchor.validate(scope=self.scope, now_ms=now_ms)
        signature = self.signature_bytes()
        if _sha(signature) != self.signature_hash:
            raise RevocationErrorV404("REVOCATION_SIGNATURE_HASH_MISMATCH")
        try:
            Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(
                signature, _canonical(self.body_for_hash())
            )
        except InvalidSignature as exc:
            raise RevocationErrorV404("REVOCATION_SIGNATURE_INVALID") from exc


class ExternalReadinessRevocationAuthorityV404:
    REVOCATION_EVENT_TYPE = "EXTERNAL_READINESS_REVALIDATION_REVOKED"
    ACCEPTED_EVENT_PREFIX = "external-readiness-revalidation:"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def revoke(
        self,
        *,
        revocation: ReadinessRevocationV404,
        reviewer_anchor: ReviewerTrustAnchorV395,
        now_ms: int,
    ) -> tuple[bool, RevalidationStatusV404, str]:
        try:
            revocation.validate(now_ms=now_ms, reviewer_anchor=reviewer_anchor)
            accepted_id = f"{self.ACCEPTED_EVENT_PREFIX}{revocation.witness_id}:accepted"
            witness_event = self.store.get(accepted_id)
            if witness_event is None:
                raise RevocationErrorV404("REVALIDATION_WITNESS_NOT_FOUND")
            if str(witness_event.payload.get("bundle_id")) != revocation.bundle_id:
                raise RevocationErrorV404("REVOCATION_BUNDLE_MISMATCH")
            if str(witness_event.payload.get("evidence_snapshot_id")) != revocation.evidence_snapshot_id:
                raise RevocationErrorV404("REVOCATION_SNAPSHOT_MISMATCH")
            if str(witness_event.payload.get("release_artifact_hash")) != revocation.release_artifact_hash:
                raise RevocationErrorV404("REVOCATION_RELEASE_HASH_MISMATCH")
            if str(witness_event.payload.get("witness_fingerprint")) != revocation.witness_fingerprint:
                raise RevocationErrorV404("REVOCATION_WITNESS_FINGERPRINT_MISMATCH")
            if not self.store.verify_chain():
                raise RevocationErrorV404("EVENT_CHAIN_INVALID")

            event_id = f"external-readiness-revalidation:{revocation.witness_id}:revoked"
            payload = {
                **revocation.body_for_hash(),
                "signature_hash": revocation.signature_hash,
                "revocation_fingerprint": revocation.fingerprint(),
                "status": RevalidationStatusV404.REVOKED.value,
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(
                    event_id=event_id,
                    occurred_at_ms=revocation.revoked_at_ms,
                    event_type=self.REVOCATION_EVENT_TYPE,
                    aggregate_id=revocation.bundle_id,
                    payload=payload,
                )
            elif existing.event_type != self.REVOCATION_EVENT_TYPE or dict(existing.payload) != payload:
                raise RevocationErrorV404("REVOCATION_EVENT_ID_CONFLICT")
            if not self.store.verify_chain():
                raise RevocationErrorV404("EVENT_CHAIN_INVALID_AFTER_REVOCATION")
            return True, RevalidationStatusV404.REVOKED, "EXTERNAL_READINESS_REVALIDATION_REVOKED"
        except (RevocationErrorV404, TrustAttestationErrorV395) as exc:
            return False, RevalidationStatusV404.REJECTED, str(exc)

    def assert_usable(self, *, witness_id: str, now_ms: int) -> None:
        accepted = self.store.get(f"{self.ACCEPTED_EVENT_PREFIX}{witness_id}:accepted")
        if accepted is None:
            raise RevocationErrorV404("REVALIDATION_WITNESS_REQUIRED")
        if not self.store.verify_chain():
            raise RevocationErrorV404("EVENT_CHAIN_INVALID")
        revoked = self.store.get(f"{self.ACCEPTED_EVENT_PREFIX}{witness_id}:revoked")
        if revoked is not None:
            raise RevocationErrorV404("REVALIDATION_WITNESS_REVOKED")
        expires_at_ms = int(accepted.payload["expires_at_ms"])
        if now_ms >= expires_at_ms:
            raise RevocationErrorV404("REVALIDATION_WITNESS_EXPIRED")
        if str(accepted.payload.get("status")) != "REVALIDATED":
            raise RevocationErrorV404("REVALIDATION_WITNESS_NOT_VALID")

    def status(self, witness_id: str, *, now_ms: int) -> RevalidationStatusV404:
        accepted = self.store.get(f"{self.ACCEPTED_EVENT_PREFIX}{witness_id}:accepted")
        if accepted is None:
            return RevalidationStatusV404.REJECTED
        if self.store.get(f"{self.ACCEPTED_EVENT_PREFIX}{witness_id}:revoked") is not None:
            return RevalidationStatusV404.REVOKED
        if now_ms >= int(accepted.payload["expires_at_ms"]):
            return RevalidationStatusV404.EXPIRED
        return RevalidationStatusV404.REVALIDATED

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v395.trust_anchor_attestation import ReviewerTrustAnchorV395, TrustAttestationErrorV395


class RevalidationErrorV403(ValueError):
    __test__ = False


class RevalidationStatusV403(str, Enum):
    VERIFIED = "VERIFIED"
    REVALIDATED = "REVALIDATED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"
    NOT_VERIFIED = "NOT_VERIFIED"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _reject_sensitive(value: Any, path: str = "root") -> None:
    forbidden = {"secret", "secrets", "private_key", "api_key", "api_secret", "password", "token", "credential", "credentials"}
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in forbidden or any(fragment in lowered for fragment in ("private_key", "api_secret", "password")):
                raise RevalidationErrorV403(f"SENSITIVE_REVALIDATION_FIELD:{path}.{key}")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{idx}]")


def _non_synthetic(ref: str, field: str) -> None:
    if not ref or ref.startswith(("demo:", "synthetic:", "fixture:", "mock:")):
        raise RevalidationErrorV403(f"{field}_REFERENCE_INVALID")


@dataclass(frozen=True)
class ReadinessRevalidationWitnessV403:
    witness_id: str
    scope: str
    bundle_id: str
    evidence_snapshot_id: str
    release_artifact_hash: str
    checked_event_hashes: tuple[tuple[str, str], ...]
    review_evidence_ref: str
    reviewer_id: str
    operator_id: str
    reviewer_key_id: str
    checked_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    def checked_events(self) -> dict[str, str]:
        return dict(self.checked_event_hashes)

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "witness_id": self.witness_id,
            "scope": self.scope,
            "bundle_id": self.bundle_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "release_artifact_hash": self.release_artifact_hash,
            "checked_event_hashes": [list(item) for item in self.checked_event_hashes],
            "review_evidence_ref": self.review_evidence_ref,
            "reviewer_id": self.reviewer_id,
            "operator_id": self.operator_id,
            "reviewer_key_id": self.reviewer_key_id,
            "checked_at_ms": self.checked_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def fingerprint(self) -> str:
        return _sha(_canonical(self.body_for_hash()))

    def signature_bytes(self) -> bytes:
        try:
            raw = b64decode(self.signature_b64.encode("ascii"), validate=True)
        except Exception as exc:
            raise RevalidationErrorV403("REVALIDATION_SIGNATURE_BASE64_INVALID") from exc
        if not raw:
            raise RevalidationErrorV403("REVALIDATION_SIGNATURE_EMPTY")
        return raw

    def validate_structure(self, *, now_ms: int, reviewer_anchor: ReviewerTrustAnchorV395, max_ttl_ms: int = 24 * 3600 * 1000) -> None:
        _reject_sensitive(self.body_for_hash())
        required = (
            self.witness_id,
            self.scope,
            self.bundle_id,
            self.evidence_snapshot_id,
            self.release_artifact_hash,
            self.review_evidence_ref,
            self.reviewer_id,
            self.operator_id,
            self.reviewer_key_id,
            self.signature_hash,
        )
        if any(not str(value) for value in required):
            raise RevalidationErrorV403("REVALIDATION_REQUIRED_FIELD_MISSING")
        if self.decision != "ACCEPT":
            raise RevalidationErrorV403("REVALIDATION_DECISION_NOT_ACCEPT")
        if self.scope != "PRODUCTION_CRITICAL":
            raise RevalidationErrorV403("REVALIDATION_SCOPE_INVALID")
        if self.reviewer_id == self.operator_id:
            raise RevalidationErrorV403("REVALIDATION_REVIEWER_OPERATOR_CONFLICT")
        _non_synthetic(self.review_evidence_ref, "REVIEW_EVIDENCE")
        pairs = self.checked_event_hashes
        if not pairs:
            raise RevalidationErrorV403("REVALIDATION_EVENT_SET_EMPTY")
        event_ids = [item[0] for item in pairs]
        if any(not event_id for event_id in event_ids) or len(set(event_ids)) != len(event_ids):
            raise RevalidationErrorV403("REVALIDATION_EVENT_SET_INVALID")
        if any(len(event_hash) != 64 for _, event_hash in pairs):
            raise RevalidationErrorV403("REVALIDATION_EVENT_HASH_INVALID")
        if self.checked_at_ms < 0 or self.expires_at_ms <= self.checked_at_ms:
            raise RevalidationErrorV403("REVALIDATION_VALIDITY_INVALID")
        if self.expires_at_ms - self.checked_at_ms > max_ttl_ms:
            raise RevalidationErrorV403("REVALIDATION_TTL_EXCEEDED")
        if not (self.checked_at_ms <= now_ms < self.expires_at_ms):
            raise RevalidationErrorV403("REVALIDATION_EXPIRED")
        if self.reviewer_key_id != reviewer_anchor.reviewer_key_id:
            raise RevalidationErrorV403("REVALIDATION_REVIEWER_KEY_MISMATCH")
        reviewer_anchor.validate(scope=self.scope, now_ms=now_ms)
        signature = self.signature_bytes()
        if _sha(signature) != self.signature_hash:
            raise RevalidationErrorV403("REVALIDATION_SIGNATURE_HASH_MISMATCH")
        try:
            Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(signature, _canonical(self.body_for_hash()))
        except InvalidSignature as exc:
            raise RevalidationErrorV403("REVALIDATION_SIGNATURE_INVALID") from exc


@dataclass(frozen=True)
class RevalidationDecisionV403:
    allowed: bool
    reason: str
    witness_id: str
    status: RevalidationStatusV403
    bundle_id: str
    evidence_snapshot_id: str


class ExternalReadinessRevalidationAuthorityV403:
    EVENT_TYPE = "EXTERNAL_READINESS_REVALIDATION_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def admit(
        self,
        *,
        witness: ReadinessRevalidationWitnessV403,
        reviewer_anchor: ReviewerTrustAnchorV395,
        now_ms: int,
    ) -> RevalidationDecisionV403:
        try:
            witness.validate_structure(now_ms=now_ms, reviewer_anchor=reviewer_anchor)
            for event_id, expected_hash in witness.checked_event_hashes:
                event = self.store.get(event_id)
                if event is None:
                    raise RevalidationErrorV403(f"REVALIDATION_EVENT_MISSING:{event_id}")
                if event.event_hash != expected_hash:
                    raise RevalidationErrorV403(f"REVALIDATION_EVENT_HASH_MISMATCH:{event_id}")
                if str(event.payload.get("status", "VERIFIED")) not in {"VERIFIED", "REVALIDATED"}:
                    raise RevalidationErrorV403(f"REVALIDATION_EVENT_NOT_VERIFIED:{event_id}")
            if not self.store.verify_chain():
                raise RevalidationErrorV403("EVENT_CHAIN_INVALID")
            event_id = f"external-readiness-revalidation:{witness.witness_id}:accepted"
            payload = {
                "witness_id": witness.witness_id,
                "scope": witness.scope,
                "bundle_id": witness.bundle_id,
                "evidence_snapshot_id": witness.evidence_snapshot_id,
                "release_artifact_hash": witness.release_artifact_hash,
                "checked_event_hashes": [list(item) for item in witness.checked_event_hashes],
                "review_evidence_ref": witness.review_evidence_ref,
                "reviewer_id": witness.reviewer_id,
                "operator_id": witness.operator_id,
                "reviewer_key_id": witness.reviewer_key_id,
                "checked_at_ms": witness.checked_at_ms,
                "expires_at_ms": witness.expires_at_ms,
                "witness_fingerprint": witness.fingerprint(),
                "status": RevalidationStatusV403.REVALIDATED.value,
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(event_id=event_id, occurred_at_ms=now_ms, event_type=self.EVENT_TYPE, aggregate_id=witness.bundle_id, payload=payload)
            elif dict(existing.payload) != payload:
                raise RevalidationErrorV403("REVALIDATION_EVENT_ID_CONFLICT")
            return RevalidationDecisionV403(True, "EXTERNAL_READINESS_REVALIDATION_ACCEPTED", witness.witness_id, RevalidationStatusV403.REVALIDATED, witness.bundle_id, witness.evidence_snapshot_id)
        except (RevalidationErrorV403, TrustAttestationErrorV395) as exc:
            status = RevalidationStatusV403.EXPIRED if "EXPIRED" in str(exc) else RevalidationStatusV403.REJECTED
            return RevalidationDecisionV403(False, str(exc), witness.witness_id, status, witness.bundle_id, witness.evidence_snapshot_id)

    def assert_fresh(self, witness_id: str, *, now_ms: int) -> None:
        event = self.store.get(f"external-readiness-revalidation:{witness_id}:accepted")
        if event is None:
            raise RevalidationErrorV403("REVALIDATION_WITNESS_REQUIRED")
        if not self.store.verify_chain():
            raise RevalidationErrorV403("EVENT_CHAIN_INVALID")
        expires_at_ms = int(event.payload["expires_at_ms"])
        if now_ms >= expires_at_ms:
            raise RevalidationErrorV403("REVALIDATION_WITNESS_EXPIRED")
        if str(event.payload.get("status")) != RevalidationStatusV403.REVALIDATED.value:
            raise RevalidationErrorV403("REVALIDATION_WITNESS_NOT_VALID")

    def get(self, witness_id: str):
        return self.store.get(f"external-readiness-revalidation:{witness_id}:accepted")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

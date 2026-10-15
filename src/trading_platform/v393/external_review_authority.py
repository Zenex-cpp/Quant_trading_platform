"""V3.93 external evidence + independent review authority.

This module closes the application-level admission boundary for critical external
readiness evidence. It does not claim to be a PKI/HSM or external-review system;
cryptographic signature authenticity remains an external operational proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from trading_platform.v21.event_store import EventStore
from trading_platform.v360.readiness_evidence import EvidenceSourceKind
from trading_platform.v361.evidence_package import EvidencePackageInvalid, validate_package


class ExternalReviewBoundaryErrorV393(ValueError):
    __test__ = False


class ReviewDecisionV393(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class SignatureVerificationStateV393(str, Enum):
    EXTERNALLY_VERIFIED = "EXTERNALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _hash(value: Mapping[str, Any]) -> str:
    return sha256(_canonical(value)).hexdigest()


def _reject_sensitive_keys(value: Any, path: str = "root") -> None:
    forbidden = {
        "secret", "secrets", "api_key", "api_secret", "private_key", "credentials",
        "credential", "access_token", "refresh_token", "password", "token", "raw_secret",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_lower = str(key).lower()
            if key_lower in forbidden or any(fragment in key_lower for fragment in ("secret", "private_key", "password")):
                raise ExternalReviewBoundaryErrorV393(f"SENSITIVE_REVIEW_FIELD:{path}.{key}")
            _reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]")


@dataclass(frozen=True)
class ExternalReviewAttestationV393:
    review_id: str
    scope: str
    subject_ids: tuple[str, ...]
    reviewer_id: str
    reviewer_role: str
    producer_ids: tuple[str, ...]
    owner_ids: tuple[str, ...]
    approver_ids: tuple[str, ...]
    decision: ReviewDecisionV393
    reviewed_at_ms: int
    expires_at_ms: int
    source_system: str
    source_ref: str
    signature_ref: str
    signature_hash: str
    signature_verification: SignatureVerificationStateV393
    review_hash: str

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "scope": self.scope,
            "subject_ids": list(self.subject_ids),
            "reviewer_id": self.reviewer_id,
            "reviewer_role": self.reviewer_role,
            "producer_ids": list(self.producer_ids),
            "owner_ids": list(self.owner_ids),
            "approver_ids": list(self.approver_ids),
            "decision": self.decision.value,
            "reviewed_at_ms": self.reviewed_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "source_system": self.source_system,
            "source_ref": self.source_ref,
            "signature_ref": self.signature_ref,
            "signature_hash": self.signature_hash,
            "signature_verification": self.signature_verification.value,
        }

    def computed_review_hash(self) -> str:
        return _hash(self.body_for_hash())

    @property
    def fingerprint(self) -> str:
        return _hash({"review_hash": self.review_hash, "review_id": self.review_id})

    def validate(self, *, now_ms: int, max_ttl_ms: int = 7 * 24 * 3600 * 1000) -> None:
        _reject_sensitive_keys(self.body_for_hash())
        if not self.review_id or not self.scope or not self.reviewer_id or not self.reviewer_role:
            raise ExternalReviewBoundaryErrorV393("REVIEW_IDENTIFIERS_REQUIRED")
        if not self.subject_ids or any(not str(v) for v in self.subject_ids):
            raise ExternalReviewBoundaryErrorV393("REVIEW_SUBJECTS_REQUIRED")
        if len(set(self.subject_ids)) != len(self.subject_ids):
            raise ExternalReviewBoundaryErrorV393("REVIEW_SUBJECTS_DUPLICATE")
        if not self.producer_ids:
            raise ExternalReviewBoundaryErrorV393("REVIEW_PRODUCER_IDS_REQUIRED")
        if self.reviewer_id in set(self.producer_ids) | set(self.owner_ids) | set(self.approver_ids):
            raise ExternalReviewBoundaryErrorV393("INDEPENDENT_REVIEWER_CONFLICT")
        if self.decision is not ReviewDecisionV393.ACCEPT:
            raise ExternalReviewBoundaryErrorV393("REVIEW_DECISION_NOT_ACCEPT")
        if self.reviewed_at_ms < 0 or self.expires_at_ms <= self.reviewed_at_ms:
            raise ExternalReviewBoundaryErrorV393("REVIEW_VALIDITY_WINDOW_INVALID")
        if self.expires_at_ms - self.reviewed_at_ms > max_ttl_ms:
            raise ExternalReviewBoundaryErrorV393("REVIEW_TTL_EXCEEDS_POLICY")
        if not (self.reviewed_at_ms <= now_ms < self.expires_at_ms):
            raise ExternalReviewBoundaryErrorV393("REVIEW_EXPIRED")
        if not self.source_system or not self.source_ref:
            raise ExternalReviewBoundaryErrorV393("REVIEW_SOURCE_REQUIRED")
        if self.source_ref.startswith(("demo:", "synthetic:")):
            raise ExternalReviewBoundaryErrorV393("SYNTHETIC_REVIEW_SOURCE_FORBIDDEN")
        if not self.signature_ref or self.signature_ref.startswith(("demo:", "synthetic:")):
            raise ExternalReviewBoundaryErrorV393("REVIEW_SIGNATURE_REFERENCE_REQUIRED")
        if not _HEX64.fullmatch(self.signature_hash.lower()):
            raise ExternalReviewBoundaryErrorV393("REVIEW_SIGNATURE_HASH_INVALID")
        if self.signature_verification is not SignatureVerificationStateV393.EXTERNALLY_VERIFIED:
            raise ExternalReviewBoundaryErrorV393("EXTERNAL_SIGNATURE_VERIFICATION_REQUIRED")
        if self.review_hash != self.computed_review_hash():
            raise ExternalReviewBoundaryErrorV393("REVIEW_HASH_MISMATCH")
        if self.source_system in set(self.producer_ids) | set(self.owner_ids):
            raise ExternalReviewBoundaryErrorV393("REVIEW_SOURCE_INDEPENDENCE_CONFLICT")

    def safe_payload(self) -> dict[str, Any]:
        return {
            **self.body_for_hash(),
            "review_hash": self.review_hash,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class ExternalReviewDecisionV393:
    allowed: bool
    reason: str
    package_id: str
    package_hash: str
    review_id: str | None
    review_hash: str | None
    evidence_ids: tuple[str, ...]
    status: str

    def safe_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "package_id": self.package_id,
            "package_hash": self.package_hash,
            "review_id": self.review_id,
            "review_hash": self.review_hash,
            "evidence_ids": list(self.evidence_ids),
            "status": self.status,
        }


class ExternalReviewAuthorityLedgerV393:
    EVENT_TYPE = "EXTERNAL_REVIEW_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def admit(
        self,
        *,
        package: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        now_ms: int,
    ) -> ExternalReviewDecisionV393:
        try:
            package_id, scope, items, package_hash = validate_package(package)
        except EvidencePackageInvalid as exc:
            return ExternalReviewDecisionV393(False, str(exc), str(package.get("package_id", "")), str(package.get("package_hash", "")), None, None, tuple(), "NOT_VERIFIED")

        try:
            if scope != review.scope:
                raise ExternalReviewBoundaryErrorV393("REVIEW_SCOPE_MISMATCH")
            review.validate(now_ms=now_ms)
            if review.source_system == str(package.get("source_system")):
                raise ExternalReviewBoundaryErrorV393("REVIEW_SOURCE_SAME_AS_PACKAGE_SOURCE")
            source_systems = {str(package.get("source_system"))} | {str(item["source_system"]) for item in items}
            if review.reviewer_id in source_systems:
                raise ExternalReviewBoundaryErrorV393("REVIEWER_SAME_AS_EVIDENCE_PRODUCER")
            required_subjects = {package_id} | {str(item["evidence_id"]) for item in items}
            if not required_subjects.issubset(set(review.subject_ids)):
                raise ExternalReviewBoundaryErrorV393("REVIEW_SUBJECT_COVERAGE_INCOMPLETE")
            if any(str(item.get("source_kind", EvidenceSourceKind.UNKNOWN.value)) != EvidenceSourceKind.EXTERNAL.value for item in items):
                raise ExternalReviewBoundaryErrorV393("EXTERNAL_EVIDENCE_REQUIRED")

            event_id = f"external-review:{review.review_id}:accepted"
            payload = {
                "review_id": review.review_id,
                "scope": review.scope,
                "package_id": package_id,
                "package_hash": package_hash,
                "review_hash": review.review_hash,
                "review_fingerprint": review.fingerprint,
                "evidence_ids": sorted(str(item["evidence_id"]) for item in items),
                "reviewer_id": review.reviewer_id,
                "reviewer_role": review.reviewer_role,
                "signature_ref": review.signature_ref,
                "signature_hash": review.signature_hash,
                "signature_verification": review.signature_verification.value,
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(
                    event_id=event_id,
                    occurred_at_ms=now_ms,
                    event_type=self.EVENT_TYPE,
                    aggregate_id=review.review_id,
                    payload=payload,
                )
            else:
                if existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
                    raise ExternalReviewBoundaryErrorV393("REVIEW_EVENT_ID_CONFLICT")
            return ExternalReviewDecisionV393(
                True,
                "EXTERNAL_REVIEW_ACCEPTED",
                package_id,
                package_hash,
                review.review_id,
                review.review_hash,
                tuple(sorted(str(item["evidence_id"]) for item in items)),
                "ACCEPTED_IN_PROCESS;EXTERNAL_SIGNATURE_PROOF_REQUIRED",
            )
        except ExternalReviewBoundaryErrorV393 as exc:
            return ExternalReviewDecisionV393(False, str(exc), package_id, package_hash, review.review_id, review.review_hash, tuple(sorted(str(item["evidence_id"]) for item in items)), "NOT_VERIFIED")

    def get(self, review_id: str):
        return self.store.get(f"external-review:{review_id}:accepted")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()

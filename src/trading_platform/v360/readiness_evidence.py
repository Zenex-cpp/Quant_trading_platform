from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Mapping

from trading_platform.v21.event_store import EventStore, canonical_json, sha256_json


class ReadinessEvidenceError(RuntimeError):
    pass


class ReadinessEvidenceConflict(ReadinessEvidenceError):
    pass


class ReadinessEvidenceInvalid(ReadinessEvidenceError):
    pass


class EvidenceState(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EvidenceResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvidenceSourceKind(str, Enum):
    EXTERNAL = "EXTERNAL"
    INTERNAL = "INTERNAL"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


REQUIRED_EVIDENCE_CLASSES = (
    "LIVE_VENUE",
    "NETWORK_SEGMENTATION",
    "SECRET_STORE",
    "BACKUP_RESTORE",
    "DISASTER_RECOVERY",
    "SECURITY_REVIEW",
    "MONITORING",
    "ROLLBACK",
    "INDEPENDENT_REVIEW",
)


@dataclass(frozen=True)
class ReadinessEvidence:
    evidence_id: str
    evidence_class: str
    scope: str
    result: EvidenceResult
    observed_at_ms: int
    valid_from_ms: int
    expires_at_ms: int
    source_system: str
    source_ref: str
    content_hash: str
    state: EvidenceState
    source_kind: EvidenceSourceKind = EvidenceSourceKind.UNKNOWN
    reviewer_id: str | None = None
    review_ref: str | None = None
    submitted_at_ms: int | None = None
    verified_at_ms: int | None = None

    def fingerprint(self) -> str:
        body = {
            "evidence_id": self.evidence_id,
            "evidence_class": self.evidence_class,
            "scope": self.scope,
            "result": self.result.value,
            "observed_at_ms": self.observed_at_ms,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
            "source_system": self.source_system,
            "source_ref": self.source_ref,
            "source_kind": self.source_kind.value,
            "content_hash": self.content_hash,
            "state": self.state.value,
            "reviewer_id": self.reviewer_id,
            "review_ref": self.review_ref,
            "submitted_at_ms": self.submitted_at_ms,
            "verified_at_ms": self.verified_at_ms,
        }
        return sha256_json(body)


class ReadinessEvidenceLedger:
    SUBMIT_EVENT = "READINESS_EVIDENCE_SUBMITTED"
    VERIFY_EVENT = "READINESS_EVIDENCE_VERIFIED"
    REJECT_EVENT = "READINESS_EVIDENCE_REJECTED"

    def __init__(self, store: EventStore):
        self.store = store

    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    @staticmethod
    def _validate_common(*, evidence_id: str, evidence_class: str, scope: str,
                         result: EvidenceResult, observed_at_ms: int,
                         valid_from_ms: int, expires_at_ms: int,
                         source_system: str, source_ref: str, content_hash: str,
                         source_kind: EvidenceSourceKind = EvidenceSourceKind.UNKNOWN) -> None:
        if not evidence_id or not evidence_class or not scope or not source_system or not source_ref:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_IDENTIFIERS_REQUIRED")
        if evidence_class not in REQUIRED_EVIDENCE_CLASSES:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_CLASS_NOT_REQUIRED")
        if result is not EvidenceResult.PASS:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_RESULT_NOT_PASS")
        if valid_from_ms > observed_at_ms or observed_at_ms > expires_at_ms:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_TIME_WINDOW_INVALID")
        if len(content_hash) != 64 or any(c not in "0123456789abcdef" for c in content_hash.lower()):
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_CONTENT_HASH_INVALID")
        if not isinstance(source_kind, EvidenceSourceKind):
            try:
                source_kind = EvidenceSourceKind(str(source_kind))
            except ValueError as exc:
                raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_SOURCE_KIND_INVALID") from exc

    def submit(self, *, evidence_id: str, evidence_class: str, scope: str,
               result: EvidenceResult, observed_at_ms: int, valid_from_ms: int,
               expires_at_ms: int, source_system: str, source_ref: str,
               content_hash: str, submitted_at_ms: int | None = None,
               source_kind: EvidenceSourceKind = EvidenceSourceKind.UNKNOWN) -> ReadinessEvidence:
        self._validate_common(
            evidence_id=evidence_id, evidence_class=evidence_class, scope=scope,
            result=result, observed_at_ms=observed_at_ms, valid_from_ms=valid_from_ms,
            expires_at_ms=expires_at_ms, source_system=source_system, source_ref=source_ref,
            content_hash=content_hash,
            source_kind=source_kind,
        )
        ts = self._now_ms() if submitted_at_ms is None else int(submitted_at_ms)
        existing = self.store.get(evidence_id)
        # Event id itself is not enough because verification creates another aggregate event.
        event_id = f"readiness-evidence:{evidence_id}:submitted"
        payload = {
            "evidence_id": evidence_id,
            "evidence_class": evidence_class,
            "scope": scope,
            "result": result.value,
            "observed_at_ms": int(observed_at_ms),
            "valid_from_ms": int(valid_from_ms),
            "expires_at_ms": int(expires_at_ms),
            "source_system": source_system,
            "source_ref": source_ref,
            "content_hash": content_hash,
            "source_kind": EvidenceSourceKind(source_kind).value,
            "submitted_at_ms": ts,
        }
        if existing is not None:
            prior = existing.payload
            if existing.event_type != self.SUBMIT_EVENT or dict(prior) != payload:
                raise ReadinessEvidenceConflict("READINESS_EVIDENCE_ID_CONFLICT")
        else:
            self.store.append(
                event_id=event_id,
                occurred_at_ms=ts,
                event_type=self.SUBMIT_EVENT,
                aggregate_id=evidence_id,
                payload=payload,
            )
        return self.get(evidence_id)

    def verify(self, *, evidence_id: str, reviewer_id: str,
               review_ref: str, verified_at_ms: int | None = None) -> ReadinessEvidence:
        if not reviewer_id or not review_ref:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_REVIEW_REQUIRED")
        current = self.get(evidence_id)
        if current is None:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_NOT_FOUND")
        if current.state is EvidenceState.REJECTED:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_REJECTED")
        if current.source_kind is not EvidenceSourceKind.EXTERNAL:
            raise ReadinessEvidenceInvalid("EXTERNAL_READINESS_EVIDENCE_REQUIRED")
        ts = self._now_ms() if verified_at_ms is None else int(verified_at_ms)
        if ts < current.valid_from_ms or ts >= current.expires_at_ms:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_VERIFICATION_OUTSIDE_WINDOW")
        if current.source_ref.startswith("demo:") or current.source_ref.startswith("synthetic:"):
            raise ReadinessEvidenceInvalid("SYNTHETIC_READINESS_EVIDENCE_FORBIDDEN")
        event_id = f"readiness-evidence:{evidence_id}:verified:{sha256(f'{reviewer_id}|{review_ref}'.encode()).hexdigest()[:16]}"
        payload = {
            "evidence_id": evidence_id,
            "reviewer_id": reviewer_id,
            "review_ref": review_ref,
            "verified_at_ms": ts,
            "content_hash": current.content_hash,
            "source_ref": current.source_ref,
        }
        try:
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(
                    event_id=event_id,
                    occurred_at_ms=ts,
                    event_type=self.VERIFY_EVENT,
                    aggregate_id=evidence_id,
                    payload=payload,
                )
        except RuntimeError as exc:
            raise ReadinessEvidenceConflict("READINESS_EVIDENCE_VERIFY_CONFLICT") from exc
        return self.get(evidence_id)

    def reject(self, *, evidence_id: str, reviewer_id: str,
               review_ref: str, rejected_at_ms: int | None = None) -> ReadinessEvidence:
        if not reviewer_id or not review_ref:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_REVIEW_REQUIRED")
        current = self.get(evidence_id)
        if current is None:
            raise ReadinessEvidenceInvalid("READINESS_EVIDENCE_NOT_FOUND")
        ts = self._now_ms() if rejected_at_ms is None else int(rejected_at_ms)
        self.store.append(
            event_id=f"readiness-evidence:{evidence_id}:rejected:{sha256(f'{reviewer_id}|{review_ref}|{ts}'.encode()).hexdigest()[:16]}",
            occurred_at_ms=ts,
            event_type=self.REJECT_EVENT,
            aggregate_id=evidence_id,
            payload={
                "evidence_id": evidence_id,
                "reviewer_id": reviewer_id,
                "review_ref": review_ref,
                "rejected_at_ms": ts,
            },
        )
        return self.get(evidence_id)

    def get(self, evidence_id: str) -> ReadinessEvidence | None:
        submitted = None
        state = None
        reviewer = None
        review_ref = None
        verified_at = None
        for event in self.store.iter_events():
            if event.aggregate_id != evidence_id:
                continue
            if event.event_type == self.SUBMIT_EVENT:
                submitted = event.payload
            elif event.event_type == self.VERIFY_EVENT:
                reviewer = event.payload.get("reviewer_id")
                review_ref = event.payload.get("review_ref")
                verified_at = int(event.payload.get("verified_at_ms"))
                state = EvidenceState.VERIFIED
            elif event.event_type == self.REJECT_EVENT:
                state = EvidenceState.REJECTED
                reviewer = event.payload.get("reviewer_id")
                review_ref = event.payload.get("review_ref")
        if submitted is None:
            return None
        if state is None:
            state = EvidenceState.SUBMITTED
        return ReadinessEvidence(
            evidence_id=evidence_id,
            evidence_class=str(submitted["evidence_class"]),
            scope=str(submitted["scope"]),
            result=EvidenceResult(str(submitted["result"])),
            observed_at_ms=int(submitted["observed_at_ms"]),
            valid_from_ms=int(submitted["valid_from_ms"]),
            expires_at_ms=int(submitted["expires_at_ms"]),
            source_system=str(submitted["source_system"]),
            source_ref=str(submitted["source_ref"]),
            source_kind=EvidenceSourceKind(str(submitted.get("source_kind", EvidenceSourceKind.UNKNOWN.value))),
            content_hash=str(submitted["content_hash"]),
            state=state,
            reviewer_id=reviewer,
            review_ref=review_ref,
            submitted_at_ms=int(submitted["submitted_at_ms"]),
            verified_at_ms=verified_at,
        )

    def verified_current(self, *, evidence_class: str, scope: str, now_ms: int) -> ReadinessEvidence | None:
        candidates = []
        for event in self.store.iter_events():
            if event.event_type != self.SUBMIT_EVENT or event.aggregate_id != str(event.aggregate_id):
                continue
            evidence = self.get(event.aggregate_id)
            if evidence is None:
                continue
            if evidence.evidence_class != evidence_class or evidence.scope != scope:
                continue
            if evidence.state is EvidenceState.VERIFIED and evidence.result is EvidenceResult.PASS:
                if evidence.valid_from_ms <= now_ms < evidence.expires_at_ms:
                    candidates.append(evidence)
        candidates.sort(key=lambda x: (x.verified_at_ms or 0, x.evidence_id), reverse=True)
        return candidates[0] if candidates else None


@dataclass(frozen=True)
class ProductionReadinessAssessment:
    assessment_id: str
    status: str
    production_ready: bool
    missing: tuple[str, ...]
    invalid: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    assessed_at_ms: int


class ProductionReadinessAssessor:
    def __init__(self, ledger: ReadinessEvidenceLedger):
        self.ledger = ledger

    def assess(self, *, assessment_id: str, scope: str, now_ms: int) -> ProductionReadinessAssessment:
        evidence_ids = []
        missing = []
        invalid = []
        for cls in REQUIRED_EVIDENCE_CLASSES:
            item = self.ledger.verified_current(evidence_class=cls, scope=scope, now_ms=now_ms)
            if item is None:
                missing.append(cls)
                continue
            evidence_ids.append(item.evidence_id)
        ready = not missing and not invalid
        return ProductionReadinessAssessment(
            assessment_id=assessment_id,
            status="READY_FOR_LIVE" if ready else "BLOCKED",
            production_ready=ready,
            missing=tuple(missing),
            invalid=tuple(invalid),
            evidence_ids=tuple(sorted(evidence_ids)),
            assessed_at_ms=int(now_ms),
        )

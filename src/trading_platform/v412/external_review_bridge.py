from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v360.readiness_evidence import (
    ReadinessEvidenceLedger,
)
from trading_platform.v361.evidence_package import (
    EvidencePackageImporter,
    EvidencePackageInvalid,
    compute_package_hash,
    validate_package,
)
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ExternalReviewAuthorityLedgerV393,
    ExternalReviewDecisionV393,
)
from trading_platform.v411.operational_evidence import (
    OperationalEvidenceManifestAuthorityV411,
    OperationalEvidenceManifestDecisionV411,
    OperationalEvidenceManifestErrorV411,
)


class ExternalReviewBridgeErrorV412(ValueError):
    __test__ = False


@dataclass(frozen=True)
class ExternalReviewBridgeRecordV412:
    bridge_id: str
    package_id: str
    scope: str
    manifest_hash: str
    review_id: str
    review_hash: str
    review_fingerprint: str
    evidence_ids: tuple[str, ...]
    evidence_fingerprints: tuple[tuple[str, str], ...]
    verified_at_ms: int

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "bridge_id": self.bridge_id,
                "package_id": self.package_id,
                "scope": self.scope,
                "manifest_hash": self.manifest_hash,
                "review_id": self.review_id,
                "review_hash": self.review_hash,
                "review_fingerprint": self.review_fingerprint,
                "evidence_ids": list(self.evidence_ids),
                "evidence_fingerprints": [list(x) for x in self.evidence_fingerprints],
                "verified_at_ms": self.verified_at_ms,
            }
        )


@dataclass(frozen=True)
class ExternalReviewBridgeDecisionV412:
    allowed: bool
    status: str
    reason: str
    package_id: str
    scope: str
    evidence_ids: tuple[str, ...]
    bridge_id: str | None
    review_id: str | None

    @property
    def externally_verified(self) -> bool:
        return self.allowed and self.status == "EXTERNALLY_VERIFIED"


class ExternalReviewBridgeAuthorityV412:
    """Bridge a complete V4.11 evidence manifest through V3.93 external review.

    The bridge never manufactures external review. It requires an already formed
    V3.93 attestation with EXTERNALLY_VERIFIED signature state, independently
    attributed reviewer identity and subject coverage. Only after that review is
    accepted does it import/verify the operational evidence into the V3.60 ledger.
    It does not perform network calls and never sets production_ready.
    """

    EVENT_TYPE = "OPERATIONAL_EVIDENCE_EXTERNAL_REVIEW_BRIDGED_V412"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self.manifest_authority = OperationalEvidenceManifestAuthorityV411(self.store)
        self.review_authority = ExternalReviewAuthorityLedgerV393(self.store)
        self.package_importer = EvidencePackageImporter(self.store)
        self.evidence_ledger = ReadinessEvidenceLedger(self.store)

    @staticmethod
    def _utc_ms(now_ms: int) -> int:
        if not isinstance(now_ms, int):
            raise ExternalReviewBridgeErrorV412("NOW_MS_MUST_BE_INT")
        return now_ms

    def _normalized_package(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        decision = self._validate_manifest(manifest)
        if not decision.allowed:
            raise ExternalReviewBridgeErrorV412(decision.reason)
        package = {
            "package_id": str(manifest["package_id"]),
            "scope": str(manifest["scope"]),
            "created_at_ms": int(manifest["created_at_ms"]),
            "source_system": str(manifest["source_system"]),
            "evidence": [],
        }
        for item in sorted(manifest["evidence"], key=lambda x: str(x["evidence_id"])):
            package["evidence"].append(
                {
                    "evidence_id": str(item["evidence_id"]),
                    "evidence_class": str(item["evidence_class"]),
                    "scope": str(item["scope"]),
                    "result": "PASS",
                    "observed_at_ms": int(item["observed_at_ms"]),
                    "valid_from_ms": int(item["valid_from_ms"]),
                    "expires_at_ms": int(item["expires_at_ms"]),
                    "source_system": str(item["source_system"]),
                    "source_ref": str(item["source_ref"]),
                    "content_hash": str(item["content_hash"]),
                    "source_kind": "EXTERNAL",
                }
            )
        package["package_hash"] = compute_package_hash(package)
        return package

    def _validate_manifest(self, manifest: Mapping[str, Any]) -> OperationalEvidenceManifestDecisionV411:
        try:
            return self.manifest_authority.admit(manifest)
        except OperationalEvidenceManifestErrorV411 as exc:
            raise ExternalReviewBridgeErrorV412(f"MANIFEST:{exc}") from exc

    @staticmethod
    def _review_accepts(*, decision: ExternalReviewDecisionV393, package_id: str) -> None:
        if not decision.allowed:
            raise ExternalReviewBridgeErrorV412(f"EXTERNAL_REVIEW:{decision.reason}")
        if decision.package_id != package_id:
            raise ExternalReviewBridgeErrorV412("EXTERNAL_REVIEW_PACKAGE_MISMATCH")
        if decision.status != "ACCEPTED_IN_PROCESS;EXTERNAL_SIGNATURE_PROOF_REQUIRED":
            raise ExternalReviewBridgeErrorV412("EXTERNAL_REVIEW_STATUS_UNEXPECTED")

    def _import_and_verify(self, *, package: Mapping[str, Any], review: ExternalReviewAttestationV393, now_ms: int) -> tuple[str, ...]:
        try:
            package_id, scope, items, package_hash = validate_package(package)
        except EvidencePackageInvalid as exc:
            raise ExternalReviewBridgeErrorV412(f"PACKAGE:{exc}") from exc
        if package_hash != str(package["package_hash"]):
            raise ExternalReviewBridgeErrorV412("PACKAGE_HASH_MISMATCH")
        if not self.package_importer.package_was_imported(package_id):
            self.package_importer.import_package(package)
        evidence_ids = tuple(sorted(str(item["evidence_id"]) for item in items))
        for evidence_id in evidence_ids:
            self.evidence_ledger.verify(
                evidence_id=evidence_id,
                reviewer_id=review.reviewer_id,
                review_ref=review.review_id,
                verified_at_ms=now_ms,
            )
        for evidence_id in evidence_ids:
            ev = self.evidence_ledger.get(evidence_id)
            if ev is None or ev.reviewer_id != review.reviewer_id or ev.review_ref != review.review_id:
                raise ExternalReviewBridgeErrorV412("EVIDENCE_VERIFICATION_NOT_PERSISTED")
        return evidence_ids

    def _persist(self, record: ExternalReviewBridgeRecordV412) -> None:
        payload = {
            "bridge_id": record.bridge_id,
            "package_id": record.package_id,
            "scope": record.scope,
            "manifest_hash": record.manifest_hash,
            "review_id": record.review_id,
            "review_hash": record.review_hash,
            "review_fingerprint": record.review_fingerprint,
            "evidence_ids": list(record.evidence_ids),
            "evidence_fingerprints": [list(x) for x in record.evidence_fingerprints],
            "verified_at_ms": record.verified_at_ms,
            "record_fingerprint": record.fingerprint,
            "source": "V412_EXTERNAL_REVIEW_BRIDGE",
        }
        existing = self.store.get(record.bridge_id)
        if existing is not None:
            if existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
                raise ExternalReviewBridgeErrorV412("BRIDGE_RECORD_CONFLICT")
            return
        self.store.append(
            event_id=record.bridge_id,
            occurred_at_ms=record.verified_at_ms,
            event_type=self.EVENT_TYPE,
            aggregate_id=record.package_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise ExternalReviewBridgeErrorV412("EVENT_CHAIN_INVALID_AFTER_BRIDGE")

    def get(self, bridge_id: str) -> ExternalReviewBridgeRecordV412 | None:
        event = self.store.get(bridge_id)
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        p = event.payload
        record = ExternalReviewBridgeRecordV412(
            bridge_id=str(p["bridge_id"]),
            package_id=str(p["package_id"]),
            scope=str(p["scope"]),
            manifest_hash=str(p["manifest_hash"]),
            review_id=str(p["review_id"]),
            review_hash=str(p["review_hash"]),
            review_fingerprint=str(p["review_fingerprint"]),
            evidence_ids=tuple(str(v) for v in p["evidence_ids"]),
            evidence_fingerprints=tuple((str(v[0]), str(v[1])) for v in p["evidence_fingerprints"]),
            verified_at_ms=int(p["verified_at_ms"]),
        )
        if str(p.get("record_fingerprint", "")) != record.fingerprint:
            raise ExternalReviewBridgeErrorV412("BRIDGE_FINGERPRINT_MISMATCH")
        return record

    def assess(
        self,
        *,
        manifest: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        now_ms: int,
        record: bool = True,
    ) -> ExternalReviewBridgeDecisionV412:
        now_ms = self._utc_ms(now_ms)
        manifest_decision = self._validate_manifest(manifest)
        package_id = manifest_decision.package_id
        scope = str(manifest["scope"])
        evidence_ids = manifest_decision.evidence_ids
        try:
            package = self._normalized_package(manifest)
            review_decision = self.review_authority.admit(package=package, review=review, now_ms=now_ms)
            self._review_accepts(decision=review_decision, package_id=package_id)
            verified_ids = self._import_and_verify(package=package, review=review, now_ms=now_ms)
            if verified_ids != evidence_ids:
                raise ExternalReviewBridgeErrorV412("EVIDENCE_SET_CHANGED")
            evidence_fingerprints = tuple(
                (eid, self.evidence_ledger.get(eid).fingerprint())  # type: ignore[union-attr]
                for eid in evidence_ids
            )
            bridge_id = f"external-review-bridge-v412:{package_id}"
            record_obj = ExternalReviewBridgeRecordV412(
                bridge_id=bridge_id,
                package_id=package_id,
                scope=scope,
                manifest_hash=manifest_decision.manifest_hash,
                review_id=review.review_id,
                review_hash=review.review_hash,
                review_fingerprint=review.fingerprint,
                evidence_ids=evidence_ids,
                evidence_fingerprints=evidence_fingerprints,
                verified_at_ms=now_ms,
            )
            if record:
                self._persist(record_obj)
            return ExternalReviewBridgeDecisionV412(
                True, "EXTERNALLY_VERIFIED", "EXTERNAL_REVIEW_BRIDGE_VERIFIED", package_id,
                scope, evidence_ids, bridge_id, review.review_id,
            )
        except ExternalReviewBridgeErrorV412:
            raise
        except Exception as exc:
            raise ExternalReviewBridgeErrorV412(f"BRIDGE:{type(exc).__name__}:{exc}") from exc

    def assert_verified(
        self,
        bridge_id: str,
        *,
        manifest: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        now_ms: int,
    ) -> ExternalReviewBridgeRecordV412:
        record = self.get(bridge_id)
        if record is None:
            raise ExternalReviewBridgeErrorV412("BRIDGE_RECORD_NOT_FOUND")
        decision = self.assess(manifest=manifest, review=review, now_ms=now_ms, record=False)
        if not decision.externally_verified:
            raise ExternalReviewBridgeErrorV412("BRIDGE_REVALIDATION_FAILED")
        if decision.package_id != record.package_id or decision.evidence_ids != record.evidence_ids:
            raise ExternalReviewBridgeErrorV412("BRIDGE_BINDING_CHANGED")
        manifest_decision = self._validate_manifest(manifest)
        if manifest_decision.manifest_hash != record.manifest_hash:
            raise ExternalReviewBridgeErrorV412("MANIFEST_FINGERPRINT_CHANGED")
        if review.review_hash != record.review_hash or review.fingerprint != record.review_fingerprint:
            raise ExternalReviewBridgeErrorV412("REVIEW_FINGERPRINT_CHANGED")
        current = tuple(
            (eid, self.evidence_ledger.get(eid).fingerprint())  # type: ignore[union-attr]
            for eid in record.evidence_ids
        )
        if current != record.evidence_fingerprints:
            raise ExternalReviewBridgeErrorV412("EVIDENCE_FINGERPRINT_CHANGED")
        return record

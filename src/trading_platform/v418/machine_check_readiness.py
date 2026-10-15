"""V4.18 authority for Master Prompt §177 mandatory machine checks.

The authority verifies that M1-M30 are completely represented, have valid
references/statuses, are covered by a durable V3.93 external-review event,
and belong to the same bundle as a V4.17 compliance decision. It does not
create external evidence, verify cryptography independently, or enable runtime
production activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import EvidencePackageInvalid, validate_package
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ExternalReviewAuthorityLedgerV393,
    ExternalReviewBoundaryErrorV393,
    SignatureVerificationStateV393,
)
from trading_platform.v413.crypto_review import (
    PromotionCryptoReviewAuthorityV413,
    PromotionCryptoReviewErrorV413,
)
from trading_platform.v417.production_readiness_compliance import (
    ALLOWED_STATUSES_V417,
    ProductionReadinessComplianceAuthorityV417,
    ProductionReadinessComplianceErrorV417,
)


class MachineCheckReadinessErrorV418(ValueError):
    __test__ = False


MANDATORY_MACHINE_CHECKS_V418: tuple[tuple[str, str], ...] = (
    ("M1", "No Order without valid RiskDecision"),
    ("M2", "No Order with expired RiskDecision"),
    ("M3", "No Order when Position = UNKNOWN"),
    ("M4", "No New Entry when stale market data"),
    ("M5", "No New Entry with expired Prediction/Signal/Opportunity/Portfolio/Risk/Intent where required"),
    ("M6", "No Production Deployment without valid Approval"),
    ("M7", "No Champion without required gates"),
    ("M8", "No Final Holdout access from tuning workflow"),
    ("M9", "No Production credential visibility from Research"),
    ("M10", "No immutable record update without version/audit"),
    ("M11", "No duplicate side effect due to retry/replay"),
    ("M12", "No double-counted fill"),
    ("M13", "No activation after critical reconciliation mismatch"),
    ("M14", "No artifact execution when compatibility fails"),
    ("M15", "No artifact deployment when integrity fails"),
    ("M16", "No live decision from configuration conflict"),
    ("M17", "No gate reuse after invalidating change"),
    ("M18", "No promotion without Evidence Snapshot"),
    ("M19", "No promotion without valid Promotion Bundle"),
    ("M20", "No risk reservation double consumption"),
    ("M21", "Higher uncertainty cannot increase risk"),
    ("M22", "Worse liquidity cannot increase allowed exposure"),
    ("M23", "Higher drawdown cannot increase risk budget"),
    ("M24", "Worse model health cannot increase risk"),
    ("M25", "Research network cannot reach production trading endpoints"),
    ("M26", "Failed methodology assumptions produce METHOD_NOT_APPLICABLE"),
    ("M27", "Final Holdout improper access invalidates dependent evidence"),
    ("M28", "Post-recovery state cannot be READY/LIVE without recovery proof"),
    ("M29", "Risk budget cannot increase solely because state worsened"),
    ("M30", "Downstream artifact cannot exist without required valid upstream dependency"),
)

_REQUIRED_COLUMNS_V418 = (
    "machine_check_id", "requirement_text", "priority", "implementation_status",
    "code_reference", "schema_reference", "test_reference", "evidence_reference",
    "review_reference", "owner", "unresolved_gap",
)
_REQUIRED_REFS_V418 = ("code_reference", "test_reference", "evidence_reference", "owner")
_REVIEW_EVENT_TYPE_V418 = "EXTERNAL_REVIEW_ACCEPTED"


def _canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class MachineCheckReadinessDecisionV418:
    allowed: bool
    status: str
    reason: str
    decision_id: str
    bundle_id: str
    compliance_decision_id: str
    matrix_hash: str
    review_id: str | None
    blocking_machine_check_ids: tuple[str, ...]
    blocking_reasons: tuple[str, ...]


class MachineCheckReadinessAuthorityV418:
    """Evaluate §177 M1-M30 with V4.17 and V3.93 durable predecessor binding."""

    EVENT_TYPE = "MACHINE_CHECK_READINESS_EVALUATED_V418"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self.compliance_authority = ProductionReadinessComplianceAuthorityV417(self.store)
        self.review_authority = ExternalReviewAuthorityLedgerV393(self.store)

    @staticmethod
    def expected_review_package_id(bundle_id: str) -> str:
        return f"MP177-{bundle_id}"

    @staticmethod
    def _normalize_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_MATRIX_SEQUENCE_REQUIRED")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise MachineCheckReadinessErrorV418("MACHINE_CHECK_ROW_MAPPING_REQUIRED")
            missing = [name for name in _REQUIRED_COLUMNS_V418 if name not in row]
            if missing:
                raise MachineCheckReadinessErrorV418("MACHINE_CHECK_COLUMNS_MISSING:" + ",".join(missing))
            item = {name: row[name] for name in _REQUIRED_COLUMNS_V418}
            check_id = str(item["machine_check_id"]).strip()
            if not check_id:
                raise MachineCheckReadinessErrorV418("MACHINE_CHECK_ID_REQUIRED")
            if check_id in seen:
                raise MachineCheckReadinessErrorV418(f"MACHINE_CHECK_DUPLICATE:{check_id}")
            seen.add(check_id)
            status = str(item["implementation_status"])
            if status not in ALLOWED_STATUSES_V417:
                raise MachineCheckReadinessErrorV418(f"MACHINE_CHECK_STATUS_INVALID:{check_id}")
            normalized.append(item)
        normalized.sort(key=lambda item: str(item["machine_check_id"]))
        return normalized

    def _require_compliance(self, compliance_decision_id: str):
        try:
            event = self.compliance_authority.get(compliance_decision_id)
        except ProductionReadinessComplianceErrorV417 as exc:
            raise MachineCheckReadinessErrorV418(f"UPSTREAM_COMPLIANCE_INVALID:{exc}") from exc
        if event is None:
            raise MachineCheckReadinessErrorV418("UPSTREAM_COMPLIANCE_DECISION_REQUIRED")
        payload = event.payload
        if str(payload.get("decision_id")) != compliance_decision_id:
            raise MachineCheckReadinessErrorV418("UPSTREAM_COMPLIANCE_ID_MISMATCH")
        if str(payload.get("bundle_id")) != str(event.aggregate_id):
            raise MachineCheckReadinessErrorV418("UPSTREAM_COMPLIANCE_BUNDLE_MISMATCH")
        if str(payload.get("status")) not in {"VERIFIED", "BLOCKED"}:
            raise MachineCheckReadinessErrorV418("UPSTREAM_COMPLIANCE_STATUS_INVALID")
        return event

    def _review_blockers(
        self,
        *,
        review: ExternalReviewAttestationV393 | None,
        review_package: Mapping[str, Any] | None,
        normalized_matrix: Sequence[Mapping[str, Any]],
        bundle_id: str,
        crypto_review_gate_id: str | None,
        now_ms: int,
    ) -> tuple[list[str], dict[str, str]]:
        reasons: list[str] = []
        facts: dict[str, str] = {}
        if review is None:
            return ["INDEPENDENT_M1_M30_REVIEW_REQUIRED"], facts

        try:
            review.validate(now_ms=now_ms)
        except ExternalReviewBoundaryErrorV393 as exc:
            reasons.append(f"EXTERNAL_REVIEW_INVALID:{exc}")

        expected_package_id = self.expected_review_package_id(bundle_id)
        facts["review_id"] = review.review_id
        facts["review_hash"] = review.review_hash
        facts["review_fingerprint"] = review.fingerprint
        facts["review_package_id"] = expected_package_id

        valid_package_hash = ""
        package_items: list[dict[str, Any]] = []
        if review_package is None:
            reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_REQUIRED")
        else:
            try:
                package_id, package_scope, package_items, valid_package_hash = validate_package(review_package)
                facts["review_package_hash"] = valid_package_hash
                if package_id != expected_package_id:
                    reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_ID_MISMATCH")
                if package_scope != "PRODUCTION":
                    reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_SCOPE_MISMATCH")
                if any(str(item.get("source_kind", "UNKNOWN")) != "EXTERNAL" for item in package_items):
                    reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_NOT_EXTERNAL")
                package_ids = {str(item["evidence_id"]) for item in package_items}
                mandatory_ids = {check_id for check_id, _ in MANDATORY_MACHINE_CHECKS_V418}
                if package_ids != mandatory_ids:
                    reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_EVIDENCE_SET_MISMATCH")
                by_check_id = {str(row["machine_check_id"]): row for row in normalized_matrix}
                mismatched_content = [
                    str(item["evidence_id"])
                    for item in package_items
                    if str(item["evidence_id"]) in by_check_id
                    and str(item.get("content_hash", "")) != _canonical_hash(by_check_id[str(item["evidence_id"])])
                ]
                if mismatched_content:
                    reasons.append("MACHINE_CHECK_REVIEW_CONTENT_HASH_MISMATCH:" + ",".join(sorted(mismatched_content)))
            except EvidencePackageInvalid as exc:
                reasons.append(f"MACHINE_CHECK_REVIEW_PACKAGE_INVALID:{exc}")

        if review.scope != "PRODUCTION":
            reasons.append("MACHINE_CHECK_REVIEW_SCOPE_NOT_PRODUCTION")
        required_subjects = {expected_package_id, bundle_id} | {check_id for check_id, _ in MANDATORY_MACHINE_CHECKS_V418}
        if not required_subjects.issubset(set(review.subject_ids)):
            reasons.append("MACHINE_CHECK_REVIEW_COVERAGE_INCOMPLETE")

        event = self.review_authority.get(review.review_id)
        if event is None or event.event_type != _REVIEW_EVENT_TYPE_V418:
            reasons.append("MACHINE_CHECK_REVIEW_NOT_DURABLE")
            return reasons, facts

        payload = event.payload
        if str(payload.get("review_id")) != review.review_id:
            reasons.append("MACHINE_CHECK_REVIEW_ID_MISMATCH")
        if str(payload.get("review_hash")) != review.review_hash:
            reasons.append("MACHINE_CHECK_REVIEW_HASH_MISMATCH")
        if str(payload.get("review_fingerprint")) != review.fingerprint:
            reasons.append("MACHINE_CHECK_REVIEW_FINGERPRINT_MISMATCH")
        if str(payload.get("package_id")) != expected_package_id:
            reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_MISMATCH")
        if valid_package_hash and str(payload.get("package_hash")) != valid_package_hash:
            reasons.append("MACHINE_CHECK_REVIEW_PACKAGE_HASH_BINDING_MISMATCH")
        expected_package_evidence_ids = sorted(str(item["evidence_id"]) for item in package_items)
        if package_items and sorted(str(value) for value in payload.get("evidence_ids", [])) != expected_package_evidence_ids:
            reasons.append("MACHINE_CHECK_REVIEW_EVIDENCE_SET_BINDING_MISMATCH")
        if str(payload.get("scope")) != "PRODUCTION":
            reasons.append("MACHINE_CHECK_REVIEW_SCOPE_MISMATCH")
        if str(payload.get("signature_verification")) != SignatureVerificationStateV393.EXTERNALLY_VERIFIED.value:
            reasons.append("MACHINE_CHECK_REVIEW_SIGNATURE_NOT_EXTERNALLY_VERIFIED")
        covered_ids = {str(value) for value in payload.get("evidence_ids", [])}
        missing_ids = [check_id for check_id, _ in MANDATORY_MACHINE_CHECKS_V418 if check_id not in covered_ids]
        if missing_ids:
            reasons.append("MACHINE_CHECK_REVIEW_EVIDENCE_COVERAGE_INCOMPLETE:" + ",".join(missing_ids))
        facts["review_package_hash"] = str(payload.get("package_hash", ""))

        if not crypto_review_gate_id:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_REQUIRED")
            return reasons, facts
        crypto_authority = PromotionCryptoReviewAuthorityV413(self.store)
        try:
            crypto_authority.assert_valid(crypto_review_gate_id)
        except PromotionCryptoReviewErrorV413 as exc:
            reasons.append(f"MACHINE_CHECK_CRYPTO_REVIEW_INVALID:{exc}")
            return reasons, facts
        crypto_event = self.store.get(crypto_review_gate_id)
        if crypto_event is None or crypto_event.event_type != PromotionCryptoReviewAuthorityV413.EVENT_TYPE:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_NOT_DURABLE")
            return reasons, facts
        crypto_payload = crypto_event.payload
        if str(crypto_payload.get("status")) != "VERIFIED":
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_NOT_VERIFIED")
        if str(crypto_payload.get("review_id")) != review.review_id:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_ID_MISMATCH")
        if str(crypto_payload.get("review_hash")) != review.review_hash:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_HASH_MISMATCH")
        if str(crypto_payload.get("package_id")) != expected_package_id:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_PACKAGE_MISMATCH")
        if str(crypto_payload.get("package_hash")) != str(payload.get("package_hash")):
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_PACKAGE_HASH_MISMATCH")
        if str(crypto_event.aggregate_id) != expected_package_id:
            reasons.append("MACHINE_CHECK_CRYPTO_REVIEW_AGGREGATE_MISMATCH")
        facts["crypto_review_gate_id"] = crypto_review_gate_id
        facts["crypto_review_fingerprint"] = str(crypto_payload.get("fingerprint", ""))
        return reasons, facts

    def evaluate(
        self,
        *,
        decision_id: str,
        compliance_decision_id: str,
        matrix: Sequence[Mapping[str, Any]],
        review: ExternalReviewAttestationV393 | None,
        now_ms: int,
        review_package: Mapping[str, Any] | None = None,
        crypto_review_gate_id: str | None = None,
    ) -> MachineCheckReadinessDecisionV418:
        if not decision_id or not compliance_decision_id:
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_DECISION_IDENTIFIERS_REQUIRED")
        if not isinstance(now_ms, int):
            raise MachineCheckReadinessErrorV418("NOW_MS_MUST_BE_INT")

        compliance_event = self._require_compliance(compliance_decision_id)
        normalized = self._normalize_matrix(matrix)
        by_id = {str(row["machine_check_id"]): row for row in normalized}
        missing = [check_id for check_id, _ in MANDATORY_MACHINE_CHECKS_V418 if check_id not in by_id]
        if missing:
            raise MachineCheckReadinessErrorV418("MANDATORY_MACHINE_CHECKS_MISSING:" + ",".join(missing))
        wrong_text = [
            check_id for check_id, expected in MANDATORY_MACHINE_CHECKS_V418
            if expected.lower() not in str(by_id[check_id]["requirement_text"]).lower()
        ]
        if wrong_text:
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_REQUIREMENT_TEXT_MISMATCH:" + ",".join(wrong_text))

        blocking_checks: list[str] = []
        for row in normalized:
            check_id = str(row["machine_check_id"])
            missing_refs = [key for key in _REQUIRED_REFS_V418 if not str(row[key]).strip()]
            unresolved = str(row["unresolved_gap"]).strip()
            if (
                str(row["implementation_status"]) != "VERIFIED"
                or missing_refs
                or unresolved
                or not str(row["review_reference"]).strip()
                or (review is not None and str(row["review_reference"]).strip() != review.review_id)
            ):
                blocking_checks.append(check_id)

        review_reasons, review_facts = self._review_blockers(
            review=review,
            review_package=review_package,
            normalized_matrix=normalized,
            bundle_id=str(compliance_event.payload["bundle_id"]),
            crypto_review_gate_id=crypto_review_gate_id,
            now_ms=now_ms,
        )
        blocking_reasons: list[str] = list(review_reasons)
        if str(compliance_event.payload.get("status")) != "VERIFIED":
            blocking_reasons.append("UPSTREAM_COMPLIANCE_NOT_VERIFIED")

        matrix_hash = _canonical_hash(normalized)
        bundle_id = str(compliance_event.payload["bundle_id"])
        result_status = "VERIFIED" if not blocking_checks and not blocking_reasons else "BLOCKED"
        reason = "MANDATORY_MACHINE_CHECKS_VERIFIED" if result_status == "VERIFIED" else "MANDATORY_MACHINE_CHECKS_NOT_VERIFIED"
        event_id = f"machine-check-readiness-v418:{decision_id}"
        payload = {
            "decision_id": decision_id,
            "compliance_decision_id": compliance_decision_id,
            "compliance_decision_fingerprint": str(compliance_event.payload.get("fingerprint", "")),
            "bundle_id": bundle_id,
            "matrix_hash": matrix_hash,
            "review_id": review_facts.get("review_id", ""),
            "review_hash": review_facts.get("review_hash", ""),
            "review_fingerprint": review_facts.get("review_fingerprint", ""),
            "review_package_id": review_facts.get("review_package_id", ""),
            "review_package_hash": review_facts.get("review_package_hash", ""),
            "crypto_review_gate_id": review_facts.get("crypto_review_gate_id", ""),
            "crypto_review_fingerprint": review_facts.get("crypto_review_fingerprint", ""),
            "blocking_machine_check_ids": blocking_checks,
            "blocking_reasons": blocking_reasons,
            "status": result_status,
            "reason": reason,
            "activation_flag": "NOT_SET",
            "production_ready": False,
        }
        payload["fingerprint"] = _canonical_hash(payload)
        existing = self.store.get(event_id)
        if existing is None:
            self.store.append(
                event_id=event_id,
                occurred_at_ms=now_ms,
                event_type=self.EVENT_TYPE,
                aggregate_id=bundle_id,
                payload=payload,
            )
        elif existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_DECISION_ID_CONFLICT")

        return MachineCheckReadinessDecisionV418(
            allowed=result_status == "VERIFIED",
            status=result_status,
            reason=reason,
            decision_id=event_id,
            bundle_id=bundle_id,
            compliance_decision_id=compliance_decision_id,
            matrix_hash=matrix_hash,
            review_id=review_facts.get("review_id"),
            blocking_machine_check_ids=tuple(blocking_checks),
            blocking_reasons=tuple(blocking_reasons),
        )

    def get(self, decision_id: str):
        event = self.store.get(f"machine-check-readiness-v418:{decision_id}")
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _canonical_hash(payload):
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_FINGERPRINT_MISMATCH")
        if payload.get("production_ready") is not False or payload.get("activation_flag") != "NOT_SET":
            raise MachineCheckReadinessErrorV418("PRODUCTION_FLAG_MUTATION_FORBIDDEN")
        return event

    def assert_valid(self, decision_id: str) -> None:
        event = self.get(decision_id)
        if event is None or str(event.payload.get("status")) != "VERIFIED":
            raise MachineCheckReadinessErrorV418("MACHINE_CHECK_DECISION_NOT_VERIFIED")

"""V4.17 compliance contract for Master Prompt §§174-176.

This authority makes the mandatory production-readiness matrix machine-checkable.
It does not manufacture evidence, grant production activation, or expose a runtime
``production_ready`` flag. A requirement can be marked VERIFIED only when the
matrix provides implementation, test and evidence references and no unresolved gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from trading_platform.v21.event_store import EventStore


class ProductionReadinessComplianceErrorV417(ValueError):
    __test__ = False


ALLOWED_STATUSES_V417 = frozenset({
    "IMPLEMENTED", "TESTED", "VERIFIED", "PARTIAL", "BLOCKED", "NOT_APPLICABLE",
})

MANDATORY_REQUIREMENTS_V417: tuple[tuple[str, str], ...] = (
    ("MP174-01", "data validation"),
    ("MP174-02", "PIT"),
    ("MP174-03", "invariants"),
    ("MP174-04", "state matrix"),
    ("MP174-05", "risk engine"),
    ("MP174-06", "kill"),
    ("MP174-07", "reconciliation"),
    ("MP174-08", "accounting"),
    ("MP174-09", "realistic execution"),
    ("MP174-10", "monitoring"),
    ("MP174-11", "security"),
    ("MP174-12", "permissions"),
    ("MP174-13", "network isolation"),
    ("MP174-14", "backup"),
    ("MP174-15", "restore"),
    ("MP174-16", "rollback"),
    ("MP174-17", "failure injection"),
    ("MP174-18", "recovery proof"),
    ("MP174-19", "evidence snapshot"),
    ("MP174-20", "promotion bundle"),
    ("MP174-21", "approval"),
)

_REQUIRED_COLUMNS_V417 = (
    "requirement_id", "requirement_text", "priority", "implementation_status",
    "code_reference", "schema_reference", "test_reference", "evidence_reference",
    "owner", "unresolved_gap",
)


def _canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProductionReadinessComplianceDecisionV417:
    allowed: bool
    status: str
    reason: str
    decision_id: str
    bundle_id: str
    convergence_id: str
    matrix_hash: str
    blocking_requirement_ids: tuple[str, ...]


class ProductionReadinessComplianceAuthorityV417:
    """Validate the completeness and final status of the §174 readiness matrix."""

    EVENT_TYPE = "PRODUCTION_READINESS_COMPLIANCE_EVALUATED_V417"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _normalize_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
            raise ProductionReadinessComplianceErrorV417("COMPLIANCE_MATRIX_SEQUENCE_REQUIRED")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise ProductionReadinessComplianceErrorV417("COMPLIANCE_ROW_MAPPING_REQUIRED")
            missing = [name for name in _REQUIRED_COLUMNS_V417 if name not in row]
            if missing:
                raise ProductionReadinessComplianceErrorV417(
                    "COMPLIANCE_COLUMNS_MISSING:" + ",".join(missing)
                )
            item = {name: row[name] for name in _REQUIRED_COLUMNS_V417}
            rid = str(item["requirement_id"])
            if not rid:
                raise ProductionReadinessComplianceErrorV417("COMPLIANCE_REQUIREMENT_ID_REQUIRED")
            if rid in seen:
                raise ProductionReadinessComplianceErrorV417(f"COMPLIANCE_DUPLICATE_REQUIREMENT:{rid}")
            seen.add(rid)
            status = str(item["implementation_status"])
            if status not in ALLOWED_STATUSES_V417:
                raise ProductionReadinessComplianceErrorV417(f"COMPLIANCE_STATUS_INVALID:{rid}")
            normalized.append(item)
        normalized.sort(key=lambda item: str(item["requirement_id"]))
        return normalized

    def _require_convergence(self, convergence_id: str):
        event_id = f"operational-readiness-convergence-v416:{convergence_id}"
        event = self.store.get(event_id)
        if event is None or event.event_type != "OPERATIONAL_READINESS_CONVERGED_V416":
            raise ProductionReadinessComplianceErrorV417("OPERATIONAL_CONVERGENCE_REQUIRED")
        if str(event.payload.get("status")) != "VERIFIED":
            raise ProductionReadinessComplianceErrorV417("OPERATIONAL_CONVERGENCE_NOT_VERIFIED")
        if str(event.payload.get("activation_flag")) != "NOT_SET":
            raise ProductionReadinessComplianceErrorV417("OPERATIONAL_CONVERGENCE_ACTIVATION_FLAG_FORBIDDEN")
        return event

    def evaluate(
        self,
        *,
        decision_id: str,
        convergence_id: str,
        matrix: Sequence[Mapping[str, Any]],
        now_ms: int,
    ) -> ProductionReadinessComplianceDecisionV417:
        if not decision_id or not convergence_id:
            raise ProductionReadinessComplianceErrorV417("COMPLIANCE_DECISION_IDENTIFIERS_REQUIRED")
        if not isinstance(now_ms, int):
            raise ProductionReadinessComplianceErrorV417("NOW_MS_MUST_BE_INT")
        convergence = self._require_convergence(convergence_id)
        normalized = self._normalize_matrix(matrix)
        by_id = {str(row["requirement_id"]): row for row in normalized}
        missing = [rid for rid, _ in MANDATORY_REQUIREMENTS_V417 if rid not in by_id]
        if missing:
            raise ProductionReadinessComplianceErrorV417(
                "MANDATORY_REQUIREMENTS_MISSING:" + ",".join(missing)
            )
        wrong_text = [
            rid for rid, expected in MANDATORY_REQUIREMENTS_V417
            if expected.lower() not in str(by_id[rid]["requirement_text"]).lower()
        ]
        if wrong_text:
            raise ProductionReadinessComplianceErrorV417(
                "MANDATORY_REQUIREMENT_TEXT_MISMATCH:" + ",".join(wrong_text)
            )

        blocking: list[str] = []
        for rid, _ in MANDATORY_REQUIREMENTS_V417:
            row = by_id[rid]
            status = str(row["implementation_status"])
            missing_refs = [
                key for key in ("code_reference", "test_reference", "evidence_reference", "owner")
                if not str(row[key]).strip()
            ]
            unresolved = str(row["unresolved_gap"]).strip()
            if status != "VERIFIED" or missing_refs or unresolved:
                blocking.append(rid)

        matrix_hash = _canonical_hash(normalized)
        bundle_id = str(convergence.payload.get("bundle_id"))
        result_status = "VERIFIED" if not blocking else "BLOCKED"
        reason = (
            "MANDATORY_READINESS_MATRIX_VERIFIED"
            if not blocking
            else "MANDATORY_READINESS_REQUIREMENTS_NOT_VERIFIED"
        )
        event_id = f"production-readiness-compliance-v417:{decision_id}"
        payload = {
            "decision_id": decision_id,
            "convergence_id": convergence_id,
            "bundle_id": bundle_id,
            "matrix_hash": matrix_hash,
            "blocking_requirement_ids": blocking,
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
        elif dict(existing.payload) != payload:
            raise ProductionReadinessComplianceErrorV417("COMPLIANCE_DECISION_ID_CONFLICT")

        return ProductionReadinessComplianceDecisionV417(
            allowed=not blocking,
            status=result_status,
            reason=reason,
            decision_id=event_id,
            bundle_id=bundle_id,
            convergence_id=convergence_id,
            matrix_hash=matrix_hash,
            blocking_requirement_ids=tuple(blocking),
        )

    def get(self, decision_id: str):
        event = self.store.get(f"production-readiness-compliance-v417:{decision_id}")
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _canonical_hash(payload):
            raise ProductionReadinessComplianceErrorV417("COMPLIANCE_FINGERPRINT_MISMATCH")
        if payload.get("production_ready") is not False or payload.get("activation_flag") != "NOT_SET":
            raise ProductionReadinessComplianceErrorV417("PRODUCTION_FLAG_MUTATION_FORBIDDEN")
        return event

    def assert_valid(self, decision_id: str) -> None:
        event = self.get(decision_id)
        if event is None or str(event.payload.get("status")) != "VERIFIED":
            raise ProductionReadinessComplianceErrorV417("COMPLIANCE_DECISION_NOT_VERIFIED")

"""V4.22 reconstructed milestone compliance preflight contract.

This module records a hash-bound decision before controlled validation. It does
not turn TESTED/PARTIAL items into VERIFIED and never grants production readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from trading_platform.v21.event_store import EventStore, LedgerEvent


class MilestonePreflightErrorV422(ValueError):
    __test__ = False


REQUIRED_COLUMNS_V422 = (
    "machine_check_id", "requirement_text", "priority", "implementation_status",
    "code_reference", "schema_reference", "test_reference", "evidence_reference",
    "review_reference", "owner", "unresolved_gap",
)
ALLOWED_STATUSES_V422 = {"IMPLEMENTED", "TESTED", "VERIFIED", "PARTIAL", "BLOCKED"}
MANDATORY_M_CHECK_IDS_V422 = tuple(f"M{i}" for i in range(1, 31))
EVENT_TYPE_V422 = "MILESTONE_COMPLIANCE_PREFLIGHT_EVALUATED_V422"


def canonical_hash_v422(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class MilestonePreflightDecisionV422:
    decision_id: str
    milestone_id: str
    status: str
    allowed: bool
    matrix_hash: str
    baseline_version: str
    baseline_sha256: str
    impacted_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    input_hashes: Mapping[str, str]
    event_hash: str
    duplicate: bool = False


class MilestoneCompliancePreflightAuthorityV422:
    EVENT_TYPE = EVENT_TYPE_V422

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def normalize_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
            raise MilestonePreflightErrorV422("COMPLIANCE_MATRIX_ROWS_REQUIRED")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise MilestonePreflightErrorV422("COMPLIANCE_ROW_MAPPING_REQUIRED")
            missing = [name for name in REQUIRED_COLUMNS_V422 if name not in row]
            if missing:
                raise MilestonePreflightErrorV422("COMPLIANCE_COLUMNS_MISSING:" + ",".join(missing))
            item = {name: str(row.get(name, "") or "").strip() for name in REQUIRED_COLUMNS_V422}
            item_id = item["machine_check_id"]
            if not item_id:
                raise MilestonePreflightErrorV422("COMPLIANCE_ID_REQUIRED")
            if item_id in seen:
                raise MilestonePreflightErrorV422(f"COMPLIANCE_ID_DUPLICATE:{item_id}")
            seen.add(item_id)
            if item["implementation_status"] not in ALLOWED_STATUSES_V422:
                raise MilestonePreflightErrorV422(f"COMPLIANCE_STATUS_INVALID:{item_id}")
            normalized.append(item)
        ids = {row["machine_check_id"] for row in normalized}
        missing_m = sorted(set(MANDATORY_M_CHECK_IDS_V422) - ids)
        if missing_m:
            raise MilestonePreflightErrorV422("MANDATORY_M_CHECKS_MISSING:" + ",".join(missing_m))
        return sorted(normalized, key=lambda row: row["machine_check_id"])

    def evaluate(
        self,
        *,
        decision_id: str,
        milestone_id: str,
        baseline_version: str,
        baseline_sha256: str,
        rows: Sequence[Mapping[str, Any]],
        impacted_ids: Sequence[str],
        input_hashes: Mapping[str, str],
        now_ms: int,
    ) -> MilestonePreflightDecisionV422:
        if not decision_id.strip() or not milestone_id.strip() or not baseline_version.strip():
            raise MilestonePreflightErrorV422("MILESTONE_AND_BASELINE_IDENTIFIERS_REQUIRED")
        if len(baseline_sha256) != 64 or any(c not in "0123456789abcdef" for c in baseline_sha256.lower()):
            raise MilestonePreflightErrorV422("BASELINE_SHA256_INVALID")
        normalized = self.normalize_matrix(rows)
        ids = tuple(sorted(set(str(v).strip() for v in impacted_ids if str(v).strip())))
        if not ids:
            raise MilestonePreflightErrorV422("IMPACTED_REQUIREMENT_REQUIRED")
        by_id = {row["machine_check_id"]: row for row in normalized}
        blockers: list[str] = []
        for req_id in ids:
            row = by_id.get(req_id)
            if row is None:
                blockers.append(f"IMPACTED_REQUIREMENT_MISSING:{req_id}")
            elif row["implementation_status"] == "BLOCKED":
                blockers.append(f"IMPACTED_REQUIREMENT_BLOCKED:{req_id}")
        matrix_hash = canonical_hash_v422(normalized)
        clean_hashes = {str(k): str(v) for k, v in sorted(input_hashes.items())}
        if not clean_hashes or any(len(v) != 64 for v in clean_hashes.values()):
            raise MilestonePreflightErrorV422("CONTRACT_INPUT_HASHES_REQUIRED")
        payload = {
            "decision_id": decision_id,
            "milestone_id": milestone_id,
            "status": "BLOCKED" if blockers else "READY_FOR_MILESTONE",
            "allowed": not blockers,
            "matrix_hash": matrix_hash,
            "baseline_version": baseline_version,
            "baseline_sha256": baseline_sha256.lower(),
            "impacted_ids": list(ids),
            "blockers": sorted(blockers),
            "input_hashes": clean_hashes,
            "production_ready": False,
            "external_evidence": False,
        }
        existing = self.store.get(decision_id)
        if existing is not None:
            if existing.event_type != EVENT_TYPE_V422 or dict(existing.payload) != payload:
                raise MilestonePreflightErrorV422("DECISION_ID_CONFLICT")
            if not self.store.verify_chain():
                raise MilestonePreflightErrorV422("EVENT_STORE_CHAIN_INVALID")
            return self._decision(existing, duplicate=True)
        event = self.store.append(
            event_id=decision_id,
            occurred_at_ms=int(now_ms),
            event_type=EVENT_TYPE_V422,
            aggregate_id=milestone_id,
            payload=payload,
        ).event
        if not self.store.verify_chain():
            raise MilestonePreflightErrorV422("EVENT_STORE_CHAIN_INVALID_AFTER_APPEND")
        return self._decision(event, duplicate=False)

    def get(self, decision_id: str) -> LedgerEvent | None:
        event = self.store.get(decision_id)
        if event is None or event.event_type != EVENT_TYPE_V422:
            return None
        return event

    def assert_current(
        self,
        decision_id: str,
        *,
        rows: Sequence[Mapping[str, Any]],
        baseline_version: str,
        baseline_sha256: str,
        input_hashes: Mapping[str, str],
    ) -> LedgerEvent:
        if not self.store.verify_chain():
            raise MilestonePreflightErrorV422("EVENT_STORE_CHAIN_INVALID")
        event = self.get(decision_id)
        if event is None:
            raise MilestonePreflightErrorV422("DURABLE_PREFLIGHT_REQUIRED")
        payload = event.payload
        expected_matrix_hash = canonical_hash_v422(self.normalize_matrix(rows))
        checks = {
            "MATRIX_HASH": (str(payload.get("matrix_hash")), expected_matrix_hash),
            "BASELINE_VERSION": (str(payload.get("baseline_version")), str(baseline_version)),
            "BASELINE_SHA256": (str(payload.get("baseline_sha256")), str(baseline_sha256).lower()),
            "INPUT_HASHES": (dict(payload.get("input_hashes", {})), {str(k): str(v) for k, v in sorted(input_hashes.items())}),
        }
        changed = [name for name, (actual, expected) in checks.items() if actual != expected]
        if changed:
            raise MilestonePreflightErrorV422("PREFLIGHT_STALE:" + ",".join(changed))
        if not payload.get("allowed") or payload.get("status") != "READY_FOR_MILESTONE":
            raise MilestonePreflightErrorV422("PREFLIGHT_NOT_ALLOWED")
        return event

    @staticmethod
    def _decision(event: LedgerEvent, *, duplicate: bool) -> MilestonePreflightDecisionV422:
        p = event.payload
        return MilestonePreflightDecisionV422(
            decision_id=str(p["decision_id"]), milestone_id=str(p["milestone_id"]),
            status=str(p["status"]), allowed=bool(p["allowed"]), matrix_hash=str(p["matrix_hash"]),
            baseline_version=str(p["baseline_version"]), baseline_sha256=str(p["baseline_sha256"]),
            impacted_ids=tuple(str(v) for v in p["impacted_ids"]),
            blockers=tuple(str(v) for v in p["blockers"]), input_hashes=dict(p["input_hashes"]),
            event_hash=event.event_hash, duplicate=duplicate,
        )

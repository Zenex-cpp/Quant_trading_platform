from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable, Mapping

from trading_platform.evidence.graph import (
    Evidence,
    EvidenceDependencyGraph,
    InvalidationImpact,
    propagate_invalidation,
)
from trading_platform.gates.contracts import Gate
from trading_platform.v21.event_store import EventStore


class InvalidationState(str, Enum):
    ACTIVE = "ACTIVE"
    REVALIDATED = "REVALIDATED"


class DependencyInvalidationError(RuntimeError):
    pass


class DependencyInvalidationConflict(DependencyInvalidationError):
    pass


class DependencyInvalidationBlocked(DependencyInvalidationError):
    pass


class DependencyRevalidationConflict(DependencyInvalidationError):
    pass


@dataclass(frozen=True)
class DependencyInvalidationRecord:
    incident_id: str
    changed_dependency: str
    graph_version_hash: str
    affected_artifacts: tuple[str, ...]
    invalidated_evidence: tuple[str, ...]
    invalidated_gates: tuple[str, ...]
    affected_candidates: tuple[str, ...]
    affected_promotions: tuple[str, ...]
    required_revalidation: tuple[str, ...]
    deployment_impact: str
    reason: str
    recorded_at_ms: int
    state: InvalidationState = InvalidationState.ACTIVE
    revalidation_id: str | None = None
    revalidated_at_ms: int | None = None

    @property
    def fingerprint(self) -> str:
        payload = {
            "incident_id": self.incident_id,
            "changed_dependency": self.changed_dependency,
            "graph_version_hash": self.graph_version_hash,
            "affected_artifacts": list(self.affected_artifacts),
            "invalidated_evidence": list(self.invalidated_evidence),
            "invalidated_gates": list(self.invalidated_gates),
            "affected_candidates": list(self.affected_candidates),
            "affected_promotions": list(self.affected_promotions),
            "required_revalidation": list(self.required_revalidation),
            "deployment_impact": self.deployment_impact,
            "reason": self.reason,
            "recorded_at_ms": self.recorded_at_ms,
        }
        return hashlib_payload(payload)


@dataclass(frozen=True)
class DependencyRevalidationRecord:
    revalidation_id: str
    incident_id: str
    validation_fingerprint: str
    evidence_refs: tuple[str, ...]
    gate_refs: tuple[str, ...]
    reviewer: str
    validated_at_ms: int
    state: InvalidationState = InvalidationState.REVALIDATED

    @property
    def fingerprint(self) -> str:
        return hashlib_payload({
            "revalidation_id": self.revalidation_id,
            "incident_id": self.incident_id,
            "validation_fingerprint": self.validation_fingerprint,
            "evidence_refs": list(self.evidence_refs),
            "gate_refs": list(self.gate_refs),
            "reviewer": self.reviewer,
            "validated_at_ms": self.validated_at_ms,
        })


def hashlib_payload(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


class DependencyInvalidationLedger:
    """Durable authority for dependency-triggered evidence invalidation.

    The graph computes the blast radius. This ledger turns that computation into
    an append-only, restart-safe control state. Active invalidation is fail-closed
    until a distinct REVALIDATED event closes the incident.
    """

    INVALIDATED_EVENT = "EVIDENCE_DEPENDENCY_INVALIDATED"
    REVALIDATED_EVENT = "EVIDENCE_DEPENDENCY_REVALIDATED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _now_ms(now: datetime | None = None) -> int:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("INVALIDATION_TIMEZONE_REQUIRED")
        return int(value.timestamp() * 1000)

    @staticmethod
    def _impact_payload(impact: InvalidationImpact, *, graph_version_hash: str, reason: str, recorded_at_ms: int) -> dict[str, object]:
        return {
            "changed_dependency": impact.changed_component,
            "graph_version_hash": graph_version_hash,
            "affected_artifacts": list(impact.affected_artifacts),
            "invalidated_evidence": list(impact.invalidated_evidence),
            "invalidated_gates": list(impact.invalidated_gates),
            "affected_candidates": list(impact.affected_candidates),
            "affected_promotions": list(impact.affected_promotions),
            "required_revalidation": list(impact.required_revalidation),
            "deployment_impact": impact.deployment_impact,
            "reason": reason,
            "recorded_at_ms": recorded_at_ms,
        }

    def invalidate(
        self,
        *,
        incident_id: str,
        changed_dependency: str,
        graph: EvidenceDependencyGraph,
        evidence_index: Mapping[str, Evidence],
        gate_dependencies: Mapping[str, tuple[str, ...]],
        candidates: Mapping[str, tuple[str, ...]],
        promotions: Mapping[str, tuple[str, ...]],
        reason: str,
        recorded_at_ms: int | None = None,
    ) -> tuple[DependencyInvalidationRecord, bool]:
        if not incident_id or not changed_dependency or not reason:
            raise ValueError("INVALIDATION_IDENTIFIERS_REQUIRED")
        if recorded_at_ms is None:
            recorded_at_ms = self._now_ms()
        if recorded_at_ms < 0:
            raise ValueError("INVALIDATION_TIMESTAMP_INVALID")
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID")

        impact = propagate_invalidation(
            graph,
            changed_dependency,
            dict(evidence_index),
            dict(gate_dependencies),
            dict(candidates),
            dict(promotions),
        )
        payload = self._impact_payload(
            impact,
            graph_version_hash=graph.version_hash(),
            reason=reason,
            recorded_at_ms=recorded_at_ms,
        )
        event_id = f"evidence-invalidation:{incident_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.INVALIDATED_EVENT:
                raise DependencyInvalidationConflict("INVALIDATION_EVENT_TYPE_CONFLICT")
            if hashlib_payload(existing.payload) != hashlib_payload(payload):
                raise DependencyInvalidationConflict("INVALIDATION_ID_CONFLICT")
            return self._record_from_event(existing), False

        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=recorded_at_ms,
            event_type=self.INVALIDATED_EVENT,
            aggregate_id=incident_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID_AFTER_APPEND")
        return self._record_from_event(result.event), not result.duplicate

    def revalidate(
        self,
        *,
        incident_id: str,
        revalidation_id: str,
        validation_fingerprint: str,
        evidence_refs: Iterable[str],
        gate_refs: Iterable[str],
        reviewer: str,
        validated_at_ms: int,
    ) -> tuple[DependencyRevalidationRecord, bool]:
        if not incident_id or not revalidation_id or not validation_fingerprint or not reviewer:
            raise ValueError("REVALIDATION_IDENTIFIERS_REQUIRED")
        if validated_at_ms < 0:
            raise ValueError("REVALIDATION_TIMESTAMP_INVALID")
        incident = self.get(incident_id)
        if incident is None:
            raise DependencyRevalidationConflict("INVALIDATION_NOT_FOUND")
        if incident.state is InvalidationState.REVALIDATED:
            existing = self._revalidation_for(incident_id)
            if existing is None or existing.revalidation_id != revalidation_id:
                raise DependencyRevalidationConflict("INVALIDATION_ALREADY_REVALIDATED")
            return existing, False

        evidence_tuple = tuple(sorted(set(evidence_refs)))
        gate_tuple = tuple(sorted(set(gate_refs)))
        payload = {
            "incident_id": incident_id,
            "validation_fingerprint": validation_fingerprint,
            "evidence_refs": list(evidence_tuple),
            "gate_refs": list(gate_tuple),
            "reviewer": reviewer,
            "validated_at_ms": validated_at_ms,
        }
        event_id = f"evidence-revalidation:{revalidation_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.REVALIDATED_EVENT or hashlib_payload(existing.payload) != hashlib_payload(payload):
                raise DependencyRevalidationConflict("REVALIDATION_ID_CONFLICT")
            return self._revalidation_from_event(existing), False

        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=validated_at_ms,
            event_type=self.REVALIDATED_EVENT,
            aggregate_id=incident_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise DependencyRevalidationConflict("EVENT_CHAIN_INVALID_AFTER_REVALIDATION")
        return self._revalidation_from_event(result.event), not result.duplicate

    def get(self, incident_id: str) -> DependencyInvalidationRecord | None:
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID")
        event = self.store.get(f"evidence-invalidation:{incident_id}")
        if event is None:
            return None
        record = self._record_from_event(event)
        revalidation = self._revalidation_for(incident_id)
        if revalidation is None:
            return record
        return DependencyInvalidationRecord(
            **{**record.__dict__, "state": InvalidationState.REVALIDATED,
               "revalidation_id": revalidation.revalidation_id, "revalidated_at_ms": revalidation.validated_at_ms}
        )

    def active_incidents(self) -> tuple[DependencyInvalidationRecord, ...]:
        records: list[DependencyInvalidationRecord] = []
        for event in self.store.iter_events():
            if event.event_type != self.INVALIDATED_EVENT:
                continue
            record = self.get(event.aggregate_id)
            if record is not None and record.state is InvalidationState.ACTIVE:
                records.append(record)
        return tuple(sorted(records, key=lambda r: r.incident_id))

    def blocked_dependencies(self, dependencies: Iterable[str]) -> tuple[str, ...]:
        wanted = set(dependencies)
        blocked: set[str] = set()
        for record in self.active_incidents():
            impact_set = {
                record.changed_dependency,
                *record.affected_artifacts,
                *record.invalidated_evidence,
                *record.invalidated_gates,
                *record.affected_candidates,
                *record.affected_promotions,
            }
            blocked.update(wanted & impact_set)
        return tuple(sorted(blocked))

    def checkpoint(self) -> int:
        """Return the durable event sequence used as a gate dependency checkpoint."""
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID")
        return self.store.latest_sequence()

    def assert_clear(self, dependencies: Iterable[str]) -> None:
        blocked = self.blocked_dependencies(dependencies)
        if blocked:
            raise DependencyInvalidationBlocked(
                "DEPENDENCY_INVALIDATION_ACTIVE:" + ",".join(blocked)
            )

    def assert_unchanged_since(self, checkpoint_sequence: int, dependencies: Iterable[str]) -> None:
        """Fail closed when a dependency was invalidated after a gate was issued.

        A later revalidation does not resurrect the old gate: the gate must be
        re-issued after the invalidating event so its dependency checkpoint moves
        past the change. This prevents stale authorization reuse after recovery.
        """
        if int(checkpoint_sequence) < 0:
            raise DependencyInvalidationBlocked("DEPENDENCY_CHECKPOINT_INVALID")
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID")
        wanted = set(str(v) for v in dependencies)
        if not wanted:
            return
        blocked: set[str] = set()
        for event in self.store.iter_events(start_sequence=int(checkpoint_sequence) + 1):
            if event.event_type != self.INVALIDATED_EVENT:
                continue
            record = self._record_from_event(event)
            impact_set = {
                record.changed_dependency,
                *record.affected_artifacts,
                *record.invalidated_evidence,
                *record.invalidated_gates,
                *record.affected_candidates,
                *record.affected_promotions,
            }
            blocked.update(wanted & impact_set)
        if blocked:
            raise DependencyInvalidationBlocked(
                "DEPENDENCY_INVALIDATION_AFTER_CHECKPOINT:" + ",".join(sorted(blocked))
            )

    def assert_gate_reusable(self, gate_id: str) -> None:
        self.assert_clear((gate_id,))

    def assert_evidence_usable(self, evidence_id: str) -> None:
        self.assert_clear((evidence_id,))

    def assert_evidence_not_holdout_contaminated(self, evidence_ids: Iterable[str]) -> None:
        """Final-holdout contamination is permanent for the evidence identity.

        Revalidation can clear the active incident for new evidence, but an evidence
        identity explicitly invalidated by FINAL_HOLDOUT_IMPROPER_ACCESS can never be
        reused as a fresh input to a new evidence snapshot.
        """
        wanted = set(str(v) for v in evidence_ids)
        if not wanted:
            return
        if not self.store.verify_chain():
            raise DependencyInvalidationError("EVENT_CHAIN_INVALID")
        contaminated: set[str] = set()
        for event in self.store.iter_events():
            if event.event_type != self.INVALIDATED_EVENT:
                continue
            payload = dict(event.payload)
            if str(payload.get("reason", "")) != "FINAL_HOLDOUT_IMPROPER_ACCESS":
                continue
            contaminated.update(wanted.intersection(str(v) for v in payload.get("invalidated_evidence", ())))
        if contaminated:
            raise DependencyInvalidationBlocked(
                "FINAL_HOLDOUT_CONTAMINATED_EVIDENCE:" + ",".join(sorted(contaminated))
            )

    def assert_promotion_usable(self, promotion_id: str) -> None:
        self.assert_clear((promotion_id,))

    def _revalidation_for(self, incident_id: str) -> DependencyRevalidationRecord | None:
        matches = [
            event for event in self.store.iter_events()
            if event.event_type == self.REVALIDATED_EVENT and event.aggregate_id == incident_id
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise DependencyRevalidationConflict("MULTIPLE_REVALIDATIONS_FOR_INCIDENT")
        return self._revalidation_from_event(matches[0])

    @staticmethod
    def _record_from_event(event) -> DependencyInvalidationRecord:
        p = event.payload
        return DependencyInvalidationRecord(
            incident_id=event.aggregate_id,
            changed_dependency=str(p["changed_dependency"]),
            graph_version_hash=str(p["graph_version_hash"]),
            affected_artifacts=tuple(p.get("affected_artifacts", ())),
            invalidated_evidence=tuple(p.get("invalidated_evidence", ())),
            invalidated_gates=tuple(p.get("invalidated_gates", ())),
            affected_candidates=tuple(p.get("affected_candidates", ())),
            affected_promotions=tuple(p.get("affected_promotions", ())),
            required_revalidation=tuple(p.get("required_revalidation", ())),
            deployment_impact=str(p["deployment_impact"]),
            reason=str(p["reason"]),
            recorded_at_ms=int(p["recorded_at_ms"]),
        )

    @staticmethod
    def _revalidation_from_event(event) -> DependencyRevalidationRecord:
        p = event.payload
        return DependencyRevalidationRecord(
            revalidation_id=event.event_id.split(":", 1)[1],
            incident_id=event.aggregate_id,
            validation_fingerprint=str(p["validation_fingerprint"]),
            evidence_refs=tuple(p.get("evidence_refs", ())),
            gate_refs=tuple(p.get("gate_refs", ())),
            reviewer=str(p["reviewer"]),
            validated_at_ms=int(p["validated_at_ms"]),
        )

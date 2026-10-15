from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationLedger,
    DependencyInvalidationRecord,
    DependencyInvalidationBlocked,
    DependencyRevalidationRecord,
)


class HoldoutCompromiseAuthorityError(RuntimeError):
    pass


class HoldoutCompromiseAuthorityInvalid(HoldoutCompromiseAuthorityError):
    pass


class HoldoutCompromiseAuthorityBlocked(HoldoutCompromiseAuthorityError):
    pass


class HoldoutCompromiseState(str, Enum):
    COMPROMISED = "COMPROMISED"


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class HoldoutCompromiseRecord:
    incident_id: str
    holdout_id: str
    holdout_version: str
    content_hash: str
    access_id: str
    actor: str
    reason: str
    invalidated_evidence: tuple[str, ...]
    invalidated_gates: tuple[str, ...]
    affected_candidates: tuple[str, ...]
    affected_promotions: tuple[str, ...]
    recorded_at_ms: int
    state: HoldoutCompromiseState = HoldoutCompromiseState.COMPROMISED

    @property
    def fingerprint(self) -> str:
        return _hash({
            "incident_id": self.incident_id,
            "holdout_id": self.holdout_id,
            "holdout_version": self.holdout_version,
            "content_hash": self.content_hash,
            "access_id": self.access_id,
            "actor": self.actor,
            "reason": self.reason,
            "invalidated_evidence": list(self.invalidated_evidence),
            "invalidated_gates": list(self.invalidated_gates),
            "affected_candidates": list(self.affected_candidates),
            "affected_promotions": list(self.affected_promotions),
            "recorded_at_ms": self.recorded_at_ms,
            "state": self.state.value,
        })


@dataclass(frozen=True)
class HoldoutReplacementRecord:
    replacement_id: str
    compromised_holdout_id: str
    new_holdout_id: str
    new_holdout_version: str
    new_content_hash: str
    reviewer: str
    registered_at_ms: int
    dependency_checkpoint_sequence: int

    @property
    def fingerprint(self) -> str:
        return _hash({
            "replacement_id": self.replacement_id,
            "compromised_holdout_id": self.compromised_holdout_id,
            "new_holdout_id": self.new_holdout_id,
            "new_holdout_version": self.new_holdout_version,
            "new_content_hash": self.new_content_hash,
            "reviewer": self.reviewer,
            "registered_at_ms": self.registered_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
        })


class HoldoutCompromiseAuthorityLedger:
    """Durable M27 state machine: COMPROMISED -> INCIDENT -> INVALIDATE -> NEW HOLDOUT -> REVALIDATE."""

    COMPROMISED_EVENT = "FINAL_HOLDOUT_COMPROMISED"
    DEPENDENT_EVIDENCE_EVENT = "FINAL_HOLDOUT_DEPENDENT_EVIDENCE_INVALIDATED"
    REPLACEMENT_EVENT = "FINAL_HOLDOUT_REPLACEMENT_REGISTERED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def declare_compromised(
        self,
        *,
        incident_id: str,
        holdout_id: str,
        holdout_version: str,
        content_hash: str,
        access_id: str,
        actor: str,
        reason: str,
        recorded_at_ms: int,
    ) -> HoldoutCompromiseRecord:
        values = (incident_id, holdout_id, holdout_version, content_hash, access_id, actor, reason)
        if not all(str(v) for v in values) or recorded_at_ms < 0:
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_COMPROMISE_IDENTIFIERS_REQUIRED")
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID")
        event_id = f"holdout-compromised:{holdout_id}"
        payload = {
            "incident_id": incident_id,
            "holdout_id": holdout_id,
            "holdout_version": holdout_version,
            "content_hash": content_hash,
            "access_id": access_id,
            "actor": actor,
            "reason": reason,
            "recorded_at_ms": recorded_at_ms,
            "state": HoldoutCompromiseState.COMPROMISED.value,
        }
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.COMPROMISED_EVENT or dict(existing.payload) != payload:
                raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_COMPROMISE_ID_CONFLICT")
            return self._from_event(existing)
        try:
            result = self.store.append_exclusive(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=self.COMPROMISED_EVENT,
                aggregate_id=holdout_id,
                payload=payload,
                exclusive_event_types=(self.COMPROMISED_EVENT,),
            )
        except RuntimeError as exc:
            if str(exc).startswith("EXCLUSIVE_AGGREGATE_TERMINAL:"):
                prior = self.store.get(event_id)
                if prior is not None:
                    return self._from_event(prior)
            raise
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID_AFTER_COMPROMISE")
        return self._from_event(result.event)

    def invalidate_dependents(
        self,
        *,
        compromise: HoldoutCompromiseRecord,
        dependency_authority: DependencyInvalidationLedger,
        graph,
        evidence_index,
        gate_dependencies,
        candidates,
        promotions,
    ) -> DependencyInvalidationRecord:
        record, _ = dependency_authority.invalidate(
            incident_id=compromise.incident_id,
            changed_dependency=compromise.holdout_id,
            graph=graph,
            evidence_index=evidence_index,
            gate_dependencies=gate_dependencies,
            candidates=candidates,
            promotions=promotions,
            reason=compromise.reason,
            recorded_at_ms=compromise.recorded_at_ms,
        )
        evidence_events = []
        for evidence_id in record.invalidated_evidence:
            event_id = f"holdout-evidence-invalidated:{compromise.incident_id}:{evidence_id}"
            evidence_events.append({
                "event_id": event_id,
                "occurred_at_ms": compromise.recorded_at_ms,
                "event_type": self.DEPENDENT_EVIDENCE_EVENT,
                "aggregate_id": evidence_id,
                "payload": {
                    "incident_id": compromise.incident_id,
                    "holdout_id": compromise.holdout_id,
                    "evidence_id": evidence_id,
                    "reason": compromise.reason,
                },
            })
        if evidence_events:
            self.store.append_atomic(evidence_events)
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID_AFTER_DEPENDENT_INVALIDATION")
        return record

    def assert_clean(self, holdout_id: str) -> None:
        if not holdout_id:
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_ID_REQUIRED")
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID")
        event = self.store.get(f"holdout-compromised:{holdout_id}")
        if event is not None:
            raise HoldoutCompromiseAuthorityBlocked("FINAL_HOLDOUT_COMPROMISED")

    def get_compromise(self, holdout_id: str) -> HoldoutCompromiseRecord | None:
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID")
        event = self.store.get(f"holdout-compromised:{holdout_id}")
        return None if event is None else self._from_event(event)

    def register_replacement(
        self,
        *,
        replacement_id: str,
        compromised_holdout_id: str,
        new_holdout_id: str,
        new_holdout_version: str,
        new_content_hash: str,
        reviewer: str,
        registered_at_ms: int,
        dependency_authority: DependencyInvalidationLedger,
    ) -> HoldoutReplacementRecord:
        if not all((replacement_id, compromised_holdout_id, new_holdout_id, new_holdout_version, new_content_hash, reviewer)):
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_REPLACEMENT_IDENTIFIERS_REQUIRED")
        if compromised_holdout_id == new_holdout_id:
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_REPLACEMENT_MUST_CHANGE_ID")
        compromise = self.get_compromise(compromised_holdout_id)
        if compromise is None:
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_COMPROMISE_NOT_FOUND")
        checkpoint = dependency_authority.checkpoint()
        payload = {
            "replacement_id": replacement_id,
            "compromised_holdout_id": compromised_holdout_id,
            "new_holdout_id": new_holdout_id,
            "new_holdout_version": new_holdout_version,
            "new_content_hash": new_content_hash,
            "reviewer": reviewer,
            "registered_at_ms": registered_at_ms,
            "dependency_checkpoint_sequence": checkpoint,
        }
        event_id = f"holdout-replacement:{replacement_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            record = self._replacement_from_event(existing)
            if record.fingerprint != _hash(payload):
                raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_REPLACEMENT_ID_CONFLICT")
            return record
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=registered_at_ms,
            event_type=self.REPLACEMENT_EVENT,
            aggregate_id=new_holdout_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise HoldoutCompromiseAuthorityError("EVENT_CHAIN_INVALID_AFTER_REPLACEMENT")
        return self._replacement_from_event(result.event)

    def assert_replacement_registered(
        self,
        *,
        compromised_holdout_id: str,
        new_holdout_id: str,
        new_holdout_version: str,
        new_content_hash: str,
        dependency_authority: DependencyInvalidationLedger,
    ) -> HoldoutReplacementRecord:
        if compromised_holdout_id == new_holdout_id:
            raise HoldoutCompromiseAuthorityBlocked("HOLDOUT_REPLACEMENT_MUST_CHANGE_ID")
        for event in self.store.iter_events():
            if event.event_type != self.REPLACEMENT_EVENT:
                continue
            record = self._replacement_from_event(event)
            if (
                record.compromised_holdout_id == compromised_holdout_id
                and record.new_holdout_id == new_holdout_id
                and record.new_holdout_version == new_holdout_version
                and record.new_content_hash == new_content_hash
            ):
                try:
                    dependency_authority.assert_unchanged_since(
                        record.dependency_checkpoint_sequence,
                        (compromised_holdout_id, new_holdout_id),
                    )
                except DependencyInvalidationBlocked as exc:
                    raise HoldoutCompromiseAuthorityBlocked("HOLDOUT_REPLACEMENT_STALE") from exc
                return record
        raise HoldoutCompromiseAuthorityBlocked("HOLDOUT_REPLACEMENT_NOT_REGISTERED")

    def revalidate_after_replacement(
        self,
        *,
        incident_id: str,
        revalidation_id: str,
        validation_fingerprint: str,
        replacement: HoldoutReplacementRecord,
        new_evidence_refs: Iterable[str],
        new_gate_refs: Iterable[str],
        reviewer: str,
        validated_at_ms: int,
        dependency_authority: DependencyInvalidationLedger,
    ) -> DependencyRevalidationRecord:
        incident = dependency_authority.get(incident_id)
        if incident is None:
            raise HoldoutCompromiseAuthorityInvalid("INVALIDATION_NOT_FOUND")
        if incident.changed_dependency != replacement.compromised_holdout_id:
            raise HoldoutCompromiseAuthorityInvalid("HOLDOUT_REPLACEMENT_INCIDENT_MISMATCH")
        invalidated = set(incident.invalidated_evidence)
        evidence_refs = tuple(sorted(set(str(v) for v in new_evidence_refs)))
        if not evidence_refs or invalidated.intersection(evidence_refs):
            raise HoldoutCompromiseAuthorityInvalid("REVALIDATION_REQUIRES_NEW_EVIDENCE")
        self.assert_replacement_registered(
            compromised_holdout_id=replacement.compromised_holdout_id,
            new_holdout_id=replacement.new_holdout_id,
            new_holdout_version=replacement.new_holdout_version,
            new_content_hash=replacement.new_content_hash,
            dependency_authority=dependency_authority,
        )
        return dependency_authority.revalidate(
            incident_id=incident_id,
            revalidation_id=revalidation_id,
            validation_fingerprint=validation_fingerprint,
            evidence_refs=evidence_refs,
            gate_refs=tuple(sorted(set(str(v) for v in new_gate_refs))),
            reviewer=reviewer,
            validated_at_ms=validated_at_ms,
        )[0]

    @staticmethod
    def _from_event(event) -> HoldoutCompromiseRecord:
        p = event.payload
        return HoldoutCompromiseRecord(
            incident_id=str(p["incident_id"]),
            holdout_id=str(p["holdout_id"]),
            holdout_version=str(p["holdout_version"]),
            content_hash=str(p["content_hash"]),
            access_id=str(p["access_id"]),
            actor=str(p["actor"]),
            reason=str(p["reason"]),
            invalidated_evidence=tuple(),
            invalidated_gates=tuple(),
            affected_candidates=tuple(),
            affected_promotions=tuple(),
            recorded_at_ms=int(p["recorded_at_ms"]),
        )

    @staticmethod
    def _replacement_from_event(event) -> HoldoutReplacementRecord:
        p = event.payload
        return HoldoutReplacementRecord(
            replacement_id=str(p["replacement_id"]),
            compromised_holdout_id=str(p["compromised_holdout_id"]),
            new_holdout_id=str(p["new_holdout_id"]),
            new_holdout_version=str(p["new_holdout_version"]),
            new_content_hash=str(p["new_content_hash"]),
            reviewer=str(p["reviewer"]),
            registered_at_ms=int(p["registered_at_ms"]),
            dependency_checkpoint_sequence=int(p["dependency_checkpoint_sequence"]),
        )

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from trading_platform.gates.contracts import Gate
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationError,
    DependencyInvalidationLedger,
)


class GateRevalidationErrorV406(ValueError):
    __test__ = False


class GateDispositionV406(str, Enum):
    CURRENT = "CURRENT"
    INVALIDATED = "INVALIDATED"
    RERUN_REQUIRED = "RERUN_REQUIRED"


@dataclass(frozen=True)
class GateRevalidationDecisionV406:
    allowed: bool
    reason: str
    gate_id: str
    run_id: str
    disposition: GateDispositionV406
    dependency_checkpoint: int
    current_checkpoint: int
    dependency_fingerprint: str


class GateRevalidationAuthorityV406:
    """Durable, fail-closed authority for reusing an existing gate.

    A gate is reusable only when all of its declared dependency identities are
    unchanged since the gate's explicit dependency checkpoint and there is no
    active dependency invalidation. Revalidation of the underlying incident does
    not resurrect the old gate; a fresh gate must be issued after the incident.
    """

    DECISION_EVENT = "GATE_REVALIDATION_DECISION"

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.dependency_authority.store is not self.store:
            raise GateRevalidationErrorV406("SHARED_EVENT_STORE_REQUIRED")

    @staticmethod
    def _dependencies(gate: Gate) -> tuple[str, ...]:
        return tuple(sorted(set(gate.input_versions) | set(gate.evidence_refs) | set(gate.required_artifacts)))

    @staticmethod
    def _fingerprint(gate: Gate, dependencies: tuple[str, ...], checkpoint: int) -> str:
        payload = {
            "gate_id": gate.gate_id,
            "run_id": gate.run_id,
            "candidate_version": gate.candidate_version,
            "input_versions": list(gate.input_versions),
            "required_artifacts": list(gate.required_artifacts),
            "evidence_refs": list(gate.evidence_refs),
            "dependencies": list(dependencies),
            "checkpoint": checkpoint,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _event_prefix(gate: Gate) -> str:
        return f"gate-revalidation:{gate.gate_id}:{gate.run_id}:"

    @classmethod
    def _event_id(cls, gate: Gate, checkpoint: int) -> str:
        return f"{cls._event_prefix(gate)}{checkpoint}"

    @classmethod
    def _latest_prior_decision(cls, gate: Gate, store: EventStore):
        prefix = cls._event_prefix(gate)
        candidates = [e for e in store.iter_events() if e.event_id.startswith(prefix)]
        return max(candidates, key=lambda e: e.sequence, default=None)

    @staticmethod
    def _decision_from_event(event) -> GateRevalidationDecisionV406:
        payload = event.payload
        return GateRevalidationDecisionV406(
            bool(payload["allowed"]),
            str(payload["reason"]),
            str(payload["gate_id"]),
            str(payload["run_id"]),
            GateDispositionV406(str(payload["disposition"])),
            int(payload["dependency_checkpoint"]),
            int(payload["current_checkpoint"]),
            str(payload["dependency_fingerprint"]),
        )

    def evaluate(
        self,
        *,
        gate: Gate,
        dependency_checkpoint: int,
        now_ms: int,
    ) -> GateRevalidationDecisionV406:
        if dependency_checkpoint < 0 or now_ms < 0:
            return GateRevalidationDecisionV406(
                False, "INVALID_TIMESTAMP", gate.gate_id, gate.run_id,
                GateDispositionV406.RERUN_REQUIRED, dependency_checkpoint, -1, "",
            )
        if not self.store.verify_chain():
            return GateRevalidationDecisionV406(
                False, "EVENT_CHAIN_INVALID", gate.gate_id, gate.run_id,
                GateDispositionV406.RERUN_REQUIRED, dependency_checkpoint, -1, "",
            )

        dependencies = self._dependencies(gate)
        prior = self._latest_prior_decision(gate, self.store)
        current_checkpoint = self.store.latest_sequence()
        if prior is not None and prior.sequence == current_checkpoint:
            if prior.event_type != self.DECISION_EVENT:
                raise GateRevalidationErrorV406("GATE_REVALIDATION_ID_CONFLICT")
            prior_decision = self._decision_from_event(prior)
            if prior_decision.dependency_checkpoint == dependency_checkpoint:
                return prior_decision
        fingerprint = self._fingerprint(gate, dependencies, dependency_checkpoint)
        try:
            self.dependency_authority.assert_clear(dependencies)
            self.dependency_authority.assert_unchanged_since(dependency_checkpoint, dependencies)
        except DependencyInvalidationBlocked as exc:
            blocked = GateRevalidationDecisionV406(
                False, str(exc), gate.gate_id, gate.run_id,
                GateDispositionV406.INVALIDATED, dependency_checkpoint, current_checkpoint, fingerprint,
            )
        except DependencyInvalidationError as exc:
            blocked = GateRevalidationDecisionV406(
                False, str(exc), gate.gate_id, gate.run_id,
                GateDispositionV406.RERUN_REQUIRED, dependency_checkpoint, current_checkpoint, fingerprint,
            )
        else:
            blocked = GateRevalidationDecisionV406(
                True, "GATE_REUSABLE", gate.gate_id, gate.run_id,
                GateDispositionV406.CURRENT, dependency_checkpoint, current_checkpoint, fingerprint,
            )

        payload = {
            "gate_id": blocked.gate_id,
            "run_id": blocked.run_id,
            "allowed": blocked.allowed,
            "reason": blocked.reason,
            "disposition": blocked.disposition.value,
            "dependency_checkpoint": blocked.dependency_checkpoint,
            "current_checkpoint": blocked.current_checkpoint,
            "dependency_fingerprint": blocked.dependency_fingerprint,
            "evaluated_at_ms": now_ms,
        }
        event_id = self._event_id(gate, current_checkpoint)
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.DECISION_EVENT or existing.payload != payload:
                raise GateRevalidationErrorV406("GATE_REVALIDATION_ID_CONFLICT")
            return self._decision_from_event(existing)
        self.store.append(
            event_id=event_id,
            occurred_at_ms=now_ms,
            event_type=self.DECISION_EVENT,
            aggregate_id=gate.gate_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise GateRevalidationErrorV406("EVENT_CHAIN_INVALID_AFTER_DECISION")
        return blocked

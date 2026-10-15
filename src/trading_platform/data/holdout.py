"""Final holdout access policy and capability-based vault.

The tuning workflow never receives a final-holdout handle. A handle can only be
opened from a durable FINAL_EVALUATION/AUDIT capability issued by HoldoutPolicy.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence, Any

from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationError
from trading_platform.v354.holdout_compromise import HoldoutCompromiseAuthorityBlocked, HoldoutCompromiseAuthorityError, HoldoutCompromiseAuthorityLedger
from trading_platform.v21.event_store import EventStore


class Workflow(str, Enum):
    TUNING="TUNING"; FINAL_EVALUATION="FINAL_EVALUATION"; AUDIT="AUDIT"


class HoldoutAccessContextRequired(PermissionError):
    pass


class HoldoutCapabilityInvalid(PermissionError):
    pass


@dataclass(frozen=True)
class HoldoutAccessContext:
    store: EventStore
    dependency_ledger: DependencyInvalidationLedger
    graph: EvidenceDependencyGraph
    evidence_index: Mapping[str, Evidence]
    gate_dependencies: Mapping[str, tuple[str, ...]]
    candidates: Mapping[str, tuple[str, ...]]
    promotions: Mapping[str, tuple[str, ...]]
    compromise_authority: HoldoutCompromiseAuthorityLedger

    @classmethod
    def build(
        cls,
        *,
        store: EventStore,
        graph: EvidenceDependencyGraph,
        evidence_index: Mapping[str, Evidence],
        gate_dependencies: Mapping[str, tuple[str, ...]],
        candidates: Mapping[str, tuple[str, ...]],
        promotions: Mapping[str, tuple[str, ...]],
    ) -> "HoldoutAccessContext":
        return cls(
            store,
            DependencyInvalidationLedger(store),
            graph,
            evidence_index,
            gate_dependencies,
            candidates,
            promotions,
            HoldoutCompromiseAuthorityLedger(store),
        )


@dataclass(frozen=True)
class HoldoutAccessRecord:
    access_id: str
    holdout_id: str
    workflow: Workflow
    actor: str
    attempted_at_ms: int
    allowed: bool
    incident_id: str | None = None
    event_hash: str | None = None


@dataclass(frozen=True)
class FinalHoldoutCapability:
    capability_id: str
    holdout_id: str
    workflow: Workflow
    actor: str
    valid_from_ms: int
    expires_at_ms: int
    nonce_digest: str

    def validate(self, *, holdout_id: str, workflow: Workflow, actor: str, now_ms: int) -> None:
        if self.holdout_id != holdout_id:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_HOLDOUT_MISMATCH")
        if self.workflow not in (Workflow.FINAL_EVALUATION, Workflow.AUDIT):
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_WORKFLOW_FORBIDDEN")
        if self.workflow is not workflow:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_WORKFLOW_MISMATCH")
        if self.actor != actor:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_ACTOR_MISMATCH")
        if now_ms < self.valid_from_ms or now_ms >= self.expires_at_ms:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_EXPIRED")
        if self.expires_at_ms <= self.valid_from_ms:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_WINDOW_INVALID")


class FinalHoldoutHandle:
    __slots__ = ("__holdout_id", "__rows", "__capability_id", "__opened_at_ms")

    def __init__(self, *, holdout_id: str, rows: Sequence[Any], capability_id: str, opened_at_ms: int) -> None:
        self.__holdout_id = holdout_id
        self.__rows = tuple(rows)
        self.__capability_id = capability_id
        self.__opened_at_ms = opened_at_ms

    @property
    def holdout_id(self) -> str:
        return self.__holdout_id

    @property
    def capability_id(self) -> str:
        return self.__capability_id

    @property
    def opened_at_ms(self) -> int:
        return self.__opened_at_ms

    def rows(self) -> tuple[Any, ...]:
        return self.__rows


class TuningDataView:
    """Explicitly excludes the final holdout and exposes only non-holdout splits."""
    __slots__ = ("__train", "__validation", "__oos")

    def __init__(self, *, train: Sequence[Any], validation: Sequence[Any], oos: Sequence[Any]) -> None:
        self.__train = tuple(train)
        self.__validation = tuple(validation)
        self.__oos = tuple(oos)

    @property
    def train(self) -> tuple[Any, ...]:
        return self.__train

    @property
    def validation(self) -> tuple[Any, ...]:
        return self.__validation

    @property
    def oos(self) -> tuple[Any, ...]:
        return self.__oos

    def __getattr__(self, name: str) -> Any:
        if name.lower() in {"final_holdout", "holdout", "final"}:
            raise AttributeError("FINAL_HOLDOUT_NOT_EXPOSED_TO_TUNING")
        raise AttributeError(name)


class HoldoutVault:
    """Durable capability-gated vault. TUNING callers have no method to open a handle."""
    __slots__ = ("__holdout_id", "__rows", "__context", "__policy")

    OPEN_EVENT = "FINAL_HOLDOUT_HANDLE_OPENED"

    def __init__(self, *, holdout_id: str, rows: Sequence[Any], context: HoldoutAccessContext, policy: "HoldoutPolicy") -> None:
        if not holdout_id or context is None or policy is None:
            raise ValueError("HOLDOUT_VAULT_CONFIGURATION_INVALID")
        if policy.holdout_id != holdout_id:
            raise ValueError("HOLDOUT_VAULT_POLICY_MISMATCH")
        self.__holdout_id = holdout_id
        self.__rows = tuple(rows)
        self.__context = context
        self.__policy = policy

    @property
    def holdout_id(self) -> str:
        return self.__holdout_id

    def open(self, *, capability: FinalHoldoutCapability, actor: str, now_ms: int) -> FinalHoldoutHandle:
        try:
            self.__context.compromise_authority.assert_clean(self.__holdout_id)
        except HoldoutCompromiseAuthorityBlocked as exc:
            raise HoldoutCapabilityInvalid("FINAL_HOLDOUT_COMPROMISED") from exc
        capability.validate(holdout_id=self.__holdout_id, workflow=capability.workflow, actor=actor, now_ms=now_ms)
        issued_id = f"holdout-capability:{capability.capability_id}"
        issued = self.__context.store.get(issued_id)
        if issued is None:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_NOT_ISSUED")
        expected_issued = {
            "capability_id": capability.capability_id,
            "holdout_id": self.__holdout_id,
            "workflow": capability.workflow.value,
            "actor": actor,
            "issued_at_ms": capability.valid_from_ms,
            "expires_at_ms": capability.expires_at_ms,
        }
        if issued.payload != expected_issued:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_PROVENANCE_MISMATCH")
        used_id = f"holdout-capability-used:{capability.capability_id}"
        if self.__context.store.get(used_id) is not None:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_ALREADY_USED")
        event_id = f"holdout-handle:{capability.capability_id}"
        if self.__context.store.get(event_id) is not None:
            raise HoldoutCapabilityInvalid("HOLDOUT_CAPABILITY_ALREADY_USED")
        if not self.__context.store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")
        payload = {
            "capability_id": capability.capability_id,
            "holdout_id": self.__holdout_id,
            "workflow": capability.workflow.value,
            "actor": actor,
            "opened_at_ms": now_ms,
        }
        self.__context.store.append(
            event_id=event_id,
            occurred_at_ms=now_ms,
            event_type=self.OPEN_EVENT,
            aggregate_id=self.__holdout_id,
            payload=payload,
        )
        self.__context.store.append(
            event_id=used_id,
            occurred_at_ms=now_ms,
            event_type="FINAL_HOLDOUT_CAPABILITY_CONSUMED",
            aggregate_id=self.__holdout_id,
            payload={"capability_id": capability.capability_id, "actor": actor},
        )
        if not self.__context.store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")
        return FinalHoldoutHandle(
            holdout_id=self.__holdout_id,
            rows=self.__rows,
            capability_id=capability.capability_id,
            opened_at_ms=now_ms,
        )


@dataclass(frozen=True)
class HoldoutPolicy:
    holdout_id: str
    immutable: bool = True
    access_logged: bool = True
    tuning_allowed: bool = False
    holdout_version: str = "1"
    content_hash: str = "UNSPECIFIED"
    replacement_of: str | None = None

    def __post_init__(self) -> None:
        if not self.holdout_id or not self.holdout_version or not self.content_hash:
            raise ValueError("HOLDOUT_ID_VERSION_HASH_REQUIRED")
        if self.replacement_of == self.holdout_id:
            raise ValueError("HOLDOUT_REPLACEMENT_MUST_CHANGE_ID")

    ACCESS_EVENT = "FINAL_HOLDOUT_ACCESS_ATTEMPTED"
    VIOLATION_EVENT = "FINAL_HOLDOUT_ACCESS_VIOLATION"
    CAPABILITY_EVENT = "FINAL_HOLDOUT_CAPABILITY_ISSUED"

    def issue_capability(
        self,
        workflow: Workflow,
        *,
        context: HoldoutAccessContext,
        capability_id: str,
        actor: str,
        issued_at_ms: int,
        ttl_ms: int = 60_000,
    ) -> FinalHoldoutCapability:
        if not context or not capability_id or not actor:
            raise HoldoutAccessContextRequired("HOLDOUT_ACCESS_CONTEXT_REQUIRED")
        if workflow is Workflow.TUNING:
            raise PermissionError("FINAL_HOLDOUT_TUNING_CAPABILITY_FORBIDDEN")
        try:
            context.compromise_authority.assert_clean(self.holdout_id)
            if self.replacement_of is not None:
                context.compromise_authority.assert_replacement_registered(
                    compromised_holdout_id=self.replacement_of,
                    new_holdout_id=self.holdout_id,
                    new_holdout_version=self.holdout_version,
                    new_content_hash=self.content_hash,
                    dependency_authority=context.dependency_ledger,
                )
        except HoldoutCompromiseAuthorityBlocked as exc:
            raise PermissionError(str(exc)) from exc
        if issued_at_ms < 0 or ttl_ms <= 0:
            raise ValueError("HOLDOUT_CAPABILITY_WINDOW_INVALID")
        if not context.store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")
        event_id = f"holdout-capability:{capability_id}"
        existing = context.store.get(event_id)
        payload = {
            "capability_id": capability_id,
            "holdout_id": self.holdout_id,
            "workflow": workflow.value,
            "actor": actor,
            "issued_at_ms": issued_at_ms,
            "expires_at_ms": issued_at_ms + ttl_ms,
        }
        if existing is not None:
            if existing.payload != payload:
                raise PermissionError("HOLDOUT_CAPABILITY_ID_CONFLICT")
        else:
            context.store.append(
                event_id=event_id,
                occurred_at_ms=issued_at_ms,
                event_type=self.CAPABILITY_EVENT,
                aggregate_id=self.holdout_id,
                payload=payload,
            )
        digest = sha256(f"{capability_id}|{self.holdout_id}|{workflow.value}|{actor}|{issued_at_ms}|{ttl_ms}".encode()).hexdigest()
        return FinalHoldoutCapability(capability_id, self.holdout_id, workflow, actor, issued_at_ms, issued_at_ms + ttl_ms, digest)

    def tuning_view(self, *, rows: Sequence[Any]) -> TuningDataView:
        if rows is None:
            raise ValueError("TUNING_DATA_REQUIRED")
        raise TypeError("TUNING_VIEW_REQUIRES_EXPLICIT_NON_HOLDOUT_SPLITS")

    def authorize(
        self,
        workflow: Workflow,
        *,
        context: HoldoutAccessContext,
        access_id: str,
        actor: str,
        attempted_at_ms: int,
    ) -> None:
        if not context or not access_id or not actor:
            raise HoldoutAccessContextRequired("HOLDOUT_ACCESS_CONTEXT_REQUIRED")
        if attempted_at_ms < 0:
            raise ValueError("HOLDOUT_ACCESS_TIMESTAMP_INVALID")
        if not context.store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")

        allowed = not (workflow == Workflow.TUNING and not self.tuning_allowed)
        if allowed:
            try:
                context.compromise_authority.assert_clean(self.holdout_id)
                if self.replacement_of is not None:
                    context.compromise_authority.assert_replacement_registered(
                        compromised_holdout_id=self.replacement_of,
                        new_holdout_id=self.holdout_id,
                        new_holdout_version=self.holdout_version,
                        new_content_hash=self.content_hash,
                        dependency_authority=context.dependency_ledger,
                    )
            except HoldoutCompromiseAuthorityBlocked as exc:
                raise PermissionError(str(exc)) from exc
        event_id = f"holdout-access:{access_id}"
        payload = {
            "access_id": access_id, "holdout_id": self.holdout_id,
            "workflow": workflow.value, "actor": actor,
            "attempted_at_ms": attempted_at_ms, "allowed": allowed,
        }
        existing = context.store.get(event_id)
        incident_id = f"holdout-access-violation:{access_id}"
        if not allowed and existing is None:
            context.compromise_authority.declare_compromised(
                incident_id=incident_id,
                holdout_id=self.holdout_id,
                holdout_version=self.holdout_version,
                content_hash=self.content_hash,
                access_id=access_id,
                actor=actor,
                reason="FINAL_HOLDOUT_IMPROPER_ACCESS",
                recorded_at_ms=attempted_at_ms,
            )
        if existing is None:
            result = context.store.append(
                event_id=event_id, occurred_at_ms=attempted_at_ms,
                event_type=self.ACCESS_EVENT, aggregate_id=self.holdout_id, payload=payload,
            )
            existing = result.event
        elif existing.payload != payload:
            raise PermissionError("HOLDOUT_ACCESS_ID_CONFLICT")

        if not allowed:
            violation_id = f"holdout-violation:{access_id}"
            violation_payload = {
                "access_id": access_id, "holdout_id": self.holdout_id,
                "workflow": workflow.value, "actor": actor,
                "attempted_at_ms": attempted_at_ms, "incident_id": incident_id,
            }
            if context.store.get(violation_id) is None:
                context.store.append(
                    event_id=violation_id, occurred_at_ms=attempted_at_ms,
                    event_type=self.VIOLATION_EVENT, aggregate_id=incident_id,
                    payload=violation_payload,
                )
            try:
                compromise = context.compromise_authority.get_compromise(self.holdout_id)
                if compromise is None:
                    raise PermissionError("FINAL_HOLDOUT_COMPROMISE_MISSING")
                context.compromise_authority.invalidate_dependents(
                    compromise=compromise,
                    dependency_authority=context.dependency_ledger,
                    graph=context.graph,
                    evidence_index=context.evidence_index,
                    gate_dependencies=context.gate_dependencies,
                    candidates=context.candidates,
                    promotions=context.promotions,
                )
            except (DependencyInvalidationError, HoldoutCompromiseAuthorityError) as exc:
                raise PermissionError("FINAL_HOLDOUT_INVALIDATION_FAILED") from exc
            raise PermissionError("FINAL_HOLDOUT_ACCESS_FORBIDDEN")

        if not context.store.verify_chain():
            raise RuntimeError("EVENT_CHAIN_INVALID")

    def audit_record(
        self, *, context: HoldoutAccessContext, access_id: str
    ) -> HoldoutAccessRecord | None:
        event = context.store.get(f"holdout-access:{access_id}")
        if event is None:
            return None
        p = event.payload
        return HoldoutAccessRecord(
            access_id=access_id, holdout_id=str(p["holdout_id"]),
            workflow=Workflow(str(p["workflow"])), actor=str(p["actor"]),
            attempted_at_ms=int(p["attempted_at_ms"]), allowed=bool(p["allowed"]),
            incident_id=(f"holdout-access-violation:{access_id}" if not bool(p["allowed"]) else None),
            event_hash=event.event_hash,
        )

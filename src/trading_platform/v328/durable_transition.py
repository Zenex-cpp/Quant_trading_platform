from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v28.deployment_authority import activation_capability_context, _issue_activation_capability, consume_activation_capability
from trading_platform.v28.deployment import (
    DeploymentEvent,
    DeploymentEventType,
    DeploymentPhase,
    DeploymentState,
)
from trading_platform.v326.transition_authority import (
    DeploymentStateTransitionAuthority,
    StateTransitionAuthorityInvalid,
    StateTransitionAuthorityRecord,
)


class DurableTransitionExecutionInvalid(RuntimeError):
    """The durable execution evidence is missing, corrupt or inconsistent."""


class DurableTransitionExecutionConflict(RuntimeError):
    """A transition execution identity was reused with incompatible content."""


@dataclass(frozen=True)
class TransitionExecutionRecord:
    transition_id: str
    deployment_id: str
    authorization_fingerprint: str
    source_phase: DeploymentPhase
    target_phase: DeploymentPhase
    source_chain_head: str
    event_sequence: int
    event_type: DeploymentEventType
    actor: str
    risk_before: Decimal
    risk_after: Decimal
    reason: str
    timestamp_ns: int
    event_hash: str
    committed_at_ms: int

    @property
    def fingerprint(self) -> str:
        return DurableTransitionExecutionLedger.fingerprint_from_payload(
            DurableTransitionExecutionLedger.payload_from_record(self)
        )


class DurableTransitionExecutionLedger:
    """Append-only commit evidence for the final deployment transition.

    The EXECUTED event contains enough deterministic transition data to replay the
    immutable DeploymentState after a crash without issuing a second activation.
    """

    EXECUTED = "DEPLOYMENT_STATE_TRANSITION_EXECUTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("EXECUTION_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def payload_from_record(cls, record: TransitionExecutionRecord) -> dict[str, Any]:
        return {
            "transition_id": record.transition_id,
            "deployment_id": record.deployment_id,
            "authorization_fingerprint": record.authorization_fingerprint,
            "source_phase": record.source_phase.value,
            "target_phase": record.target_phase.value,
            "source_chain_head": record.source_chain_head,
            "event_sequence": record.event_sequence,
            "event_type": record.event_type.value,
            "actor": record.actor,
            "risk_before": str(record.risk_before),
            "risk_after": str(record.risk_after),
            "reason": record.reason,
            "timestamp_ns": record.timestamp_ns,
            "event_hash": record.event_hash,
            "committed_at_ms": record.committed_at_ms,
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> TransitionExecutionRecord:
        try:
            record = TransitionExecutionRecord(
                transition_id=str(payload["transition_id"]),
                deployment_id=str(payload["deployment_id"]),
                authorization_fingerprint=str(payload["authorization_fingerprint"]),
                source_phase=DeploymentPhase(str(payload["source_phase"])),
                target_phase=DeploymentPhase(str(payload["target_phase"])),
                source_chain_head=str(payload["source_chain_head"]),
                event_sequence=int(payload["event_sequence"]),
                event_type=DeploymentEventType(str(payload["event_type"])),
                actor=str(payload["actor"]),
                risk_before=Decimal(str(payload["risk_before"])),
                risk_after=Decimal(str(payload["risk_after"])),
                reason=str(payload["reason"]),
                timestamp_ns=int(payload["timestamp_ns"]),
                event_hash=str(payload["event_hash"]),
                committed_at_ms=int(payload["committed_at_ms"]),
            )
        except Exception as exc:
            raise DurableTransitionExecutionInvalid("INVALID_TRANSITION_EXECUTION_PAYLOAD") from exc
        if not all((record.transition_id, record.deployment_id, record.authorization_fingerprint,
                    record.source_chain_head, record.actor, record.reason, record.event_hash)):
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_IDENTIFIERS_REQUIRED")
        if record.event_sequence < 1 or record.timestamp_ns < 0 or record.committed_at_ms < 0:
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_NUMERIC_INVALID")
        if not record.risk_before.is_finite() or not record.risk_after.is_finite() or record.risk_before < 0 or record.risk_after < 0:
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_RISK_INVALID")
        if record.event_type is not DeploymentEventType.ACTIVATE:
            raise DurableTransitionExecutionInvalid("FINAL_ACTIVATION_EVENT_REQUIRED")
        if record.source_phase is not DeploymentPhase.CANARY or record.target_phase is not DeploymentPhase.ACTIVATED:
            raise DurableTransitionExecutionInvalid("FINAL_ACTIVATION_PHASES_REQUIRED")
        return record

    @classmethod
    def from_expected_event(
        cls,
        *,
        authorization: StateTransitionAuthorityRecord,
        event: DeploymentEvent,
        committed_at_ms: int,
    ) -> TransitionExecutionRecord:
        if authorization.transition_id == "":
            raise DurableTransitionExecutionInvalid("TRANSITION_ID_REQUIRED")
        if event.deployment_id != authorization.deployment_id:
            raise DurableTransitionExecutionConflict("EXECUTION_DEPLOYMENT_MISMATCH")
        if event.from_phase is not authorization.source_phase or event.to_phase is not authorization.target_phase:
            raise DurableTransitionExecutionConflict("EXECUTION_PHASE_MISMATCH")
        if event.event_type is not DeploymentEventType.ACTIVATE:
            raise DurableTransitionExecutionInvalid("FINAL_ACTIVATION_EVENT_REQUIRED")
        if event.previous_hash != authorization_state_chain_head(authorization):
            raise DurableTransitionExecutionConflict("EXECUTION_CHAIN_BINDING_MISMATCH")
        if committed_at_ms < 0:
            raise DurableTransitionExecutionInvalid("EXECUTION_TIMESTAMP_INVALID")
        return cls._from_payload({
            "transition_id": authorization.transition_id,
            "deployment_id": authorization.deployment_id,
            "authorization_fingerprint": authorization.fingerprint,
            "source_phase": event.from_phase.value,
            "target_phase": event.to_phase.value,
            "source_chain_head": event.previous_hash,
            "event_sequence": event.sequence,
            "event_type": event.event_type.value,
            "actor": event.actor,
            "risk_before": str(event.risk_before),
            "risk_after": str(event.risk_after),
            "reason": event.reason,
            "timestamp_ns": event.timestamp_ns,
            "event_hash": event.event_hash,
            "committed_at_ms": committed_at_ms,
        })

    @classmethod
    def _event_id(cls, transition_id: str) -> str:
        return f"deployment-transition:execute:{transition_id}"

    def record(self, record: TransitionExecutionRecord) -> tuple[TransitionExecutionRecord, bool]:
        if not self.store.verify_chain():
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_EVENT_CHAIN_INVALID")
        auth_event = self.store.get(f"deployment-transition:authorize:{record.transition_id}")
        if auth_event is None:
            raise DurableTransitionExecutionInvalid("TRANSITION_AUTHORIZATION_NOT_FOUND")
        if auth_event.event_type != "DEPLOYMENT_STATE_TRANSITION_AUTHORIZED":
            raise DurableTransitionExecutionConflict("TRANSITION_AUTHORIZATION_EVENT_TYPE_MISMATCH")
        if auth_event.aggregate_id != record.deployment_id:
            raise DurableTransitionExecutionConflict("TRANSITION_AUTHORIZATION_DEPLOYMENT_MISMATCH")
        authorization_fingerprint = self.fingerprint_from_payload(auth_event.payload)
        if authorization_fingerprint != record.authorization_fingerprint:
            raise DurableTransitionExecutionConflict("TRANSITION_AUTHORIZATION_FINGERPRINT_MISMATCH")

        payload = self.payload_from_record(record)
        event_id = self._event_id(record.transition_id)
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.EXECUTED:
                raise DurableTransitionExecutionConflict("EXECUTION_EVENT_TYPE_CONFLICT")
            restored = self._from_payload(existing.payload)
            if self.fingerprint_from_payload(payload) != self.fingerprint_from_payload(self.payload_from_record(restored)):
                raise DurableTransitionExecutionConflict("TRANSITION_EXECUTION_ID_CONFLICT")
            return restored, False
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=record.committed_at_ms,
                event_type=self.EXECUTED,
                aggregate_id=record.deployment_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            concurrent = self.store.get(event_id)
            if concurrent is None:
                raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_CONCURRENT_APPEND_UNRESOLVED") from exc
            restored = self._from_payload(concurrent.payload)
            if self.fingerprint_from_payload(payload) != self.fingerprint_from_payload(self.payload_from_record(restored)):
                raise DurableTransitionExecutionConflict("TRANSITION_EXECUTION_CONCURRENT_CONFLICT") from exc
            return restored, False
        if not self.store.verify_chain():
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_EVENT_CHAIN_INVALID")
        return self._from_payload(result.event.payload), True

    def get(self, transition_id: str) -> TransitionExecutionRecord | None:
        if not self.store.verify_chain():
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_EVENT_CHAIN_INVALID")
        event = self.store.get(self._event_id(transition_id))
        if event is None:
            return None
        if event.event_type != self.EXECUTED:
            raise DurableTransitionExecutionInvalid("TRANSITION_EXECUTION_EVENT_TYPE_MISMATCH")
        record = self._from_payload(event.payload)
        if record.transition_id != transition_id:
            raise DurableTransitionExecutionConflict("TRANSITION_EXECUTION_ID_MISMATCH")
        return record

    def restore(self, state: DeploymentState, record: TransitionExecutionRecord) -> DeploymentState:
        if state.request.deployment_id != record.deployment_id:
            raise DurableTransitionExecutionConflict("RESTORE_DEPLOYMENT_MISMATCH")
        if state.phase is not record.source_phase:
            if state.phase is record.target_phase and state.chain.head_hash == record.event_hash:
                return state
            raise DurableTransitionExecutionConflict("RESTORE_SOURCE_PHASE_MISMATCH")
        if state.chain.head_hash != record.source_chain_head:
            raise DurableTransitionExecutionConflict("RESTORE_CHAIN_HEAD_MISMATCH")
        event = DeploymentEvent.build(
            sequence=record.event_sequence,
            event_type=record.event_type,
            deployment_id=record.deployment_id,
            actor=record.actor,
            from_phase=record.source_phase,
            to_phase=record.target_phase,
            risk_before=record.risk_before,
            risk_after=record.risk_after,
            reason=record.reason,
            timestamp_ns=record.timestamp_ns,
            previous_hash=record.source_chain_head,
        )
        if event.event_hash != record.event_hash:
            raise DurableTransitionExecutionInvalid("RESTORE_EVENT_HASH_MISMATCH")
        chain = state.chain.append(event)
        return DeploymentState(
            request=state.request,
            phase=record.target_phase,
            allocated_risk=record.risk_after,
            chain=chain,
            failure_reason=state.failure_reason,
        )


def authorization_state_chain_head(authorization: StateTransitionAuthorityRecord) -> str:
    # V3.26's authorization fingerprint is external to the deployment audit chain.
    # V3.28 binds execution to the pre-transition chain head carried by the state.
    # The helper exists only to make the contract explicit; callers must overwrite
    # it with the actual state chain head when constructing an execution record.
    return getattr(authorization, "state_chain_head", "")


class DurableFinalActivationAuthority:
    """Crash-safe final activation coordinator built on V3.26 authority."""

    def __init__(self, authority: DeploymentStateTransitionAuthority,
                 execution_ledger: DurableTransitionExecutionLedger) -> None:
        self.authority = authority
        self.execution_ledger = execution_ledger

    def execute(
        self,
        state: DeploymentState,
        *,
        now: datetime,
        now_ns: int,
        current_state_fingerprint: str,
        current_truth_hash: str,
        current_promotion_fingerprint: str,
        current_approval: Any,
        operator: str,
        decision_id: str,
        transition_id: str,
        orchestrator: Any,
    ) -> DeploymentState:
        prior = self.execution_ledger.get(transition_id)
        if prior is not None:
            auth = self.authority.transition_ledger.get(transition_id)
            if auth is None or auth.fingerprint != prior.authorization_fingerprint:
                raise DurableTransitionExecutionConflict("EXECUTION_AUTHORIZATION_MISMATCH")
            return self.execution_ledger.restore(state, prior)

        auth = self.authority.authorize_final_activation(
            state,
            now=now,
            now_ns=now_ns,
            current_state_fingerprint=current_state_fingerprint,
            current_truth_hash=current_truth_hash,
            current_promotion_fingerprint=current_promotion_fingerprint,
            current_approval=current_approval,
            operator=operator,
            decision_id=decision_id,
            transition_id=transition_id,
        )

        # Plan the exact immutable post-state before writing the durable execution event.
        capability = _issue_activation_capability(
            deployment_id=auth.deployment_id,
            activation_fingerprint=auth.activation_fingerprint,
            target_mode=state.request.runtime_state.mode.value,
            effective_risk=auth.effective_risk,
            valid_from=auth.valid_from,
            expires_at=auth.expires_at,
        )
        with activation_capability_context(capability):
            planned = orchestrator.plan_activate(state, now=now, now_ns=now_ns)

            expected_event = planned.chain.events[-1]
            execution_record = TransitionExecutionRecord(
                transition_id=auth.transition_id,
                deployment_id=auth.deployment_id,
                authorization_fingerprint=auth.fingerprint,
                source_phase=expected_event.from_phase,
                target_phase=expected_event.to_phase,
                source_chain_head=expected_event.previous_hash,
                event_sequence=expected_event.sequence,
                event_type=expected_event.event_type,
                actor=expected_event.actor,
                risk_before=expected_event.risk_before,
                risk_after=expected_event.risk_after,
                reason=expected_event.reason,
                timestamp_ns=expected_event.timestamp_ns,
                event_hash=expected_event.event_hash,
                committed_at_ms=now_ns // 1_000_000,
            )
            stored, _ = self.execution_ledger.record(execution_record)
            # V3.27 capability remains single-use: durable execution evidence is the commit barrier.
            consume_activation_capability(capability)

        restored = self.execution_ledger.restore(state, stored)
        return restored

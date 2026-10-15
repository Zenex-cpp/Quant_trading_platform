from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.promotion.contracts import Approval
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentState
from trading_platform.v28.deployment_authority import activation_capability_context, _issue_activation_capability
from trading_platform.v325.deployment_activation import DeploymentActivationLedger, ActivationInvalid
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v21.event_store import EventStore
from trading_platform.v357.downstream_dependency import DependencyReference, DownstreamDependencyAuthorityLedger
from trading_platform.state.enums import OperationalMode


class StateTransitionAuthorityInvalid(RuntimeError):
    """The final state transition is not authorized or cannot be proven."""


class StateTransitionAuthorityConflict(RuntimeError):
    """A transition identity was reused with different content."""


class TransitionStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    EXECUTED = "EXECUTED"


@dataclass(frozen=True)
class StateTransitionAuthorityRecord:
    transition_id: str
    deployment_id: str
    source_phase: DeploymentPhase
    target_phase: DeploymentPhase
    activation_fingerprint: str
    state_fingerprint: str
    truth_hash: str
    requested_risk: Decimal
    effective_risk: Decimal
    authorized_at: datetime
    status: TransitionStatus
    operator: str
    decision_id: str
    recorded_at_ms: int
    valid_from: datetime
    expires_at: datetime
    state_chain_head: str = ""
    recovery_proof_id: str = ""
    recovery_proof_fingerprint: str = ""

    @property
    def fingerprint(self) -> str:
        return StateTransitionAuthorityLedger.fingerprint_from_payload(
            StateTransitionAuthorityLedger.payload_from_record(self)
        )


class StateTransitionAuthorityLedger:
    RECORDED = "DEPLOYMENT_STATE_TRANSITION_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("TRANSITION_AUTHORITY_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def payload_from_record(cls, record: StateTransitionAuthorityRecord) -> dict[str, Any]:
        return {
            "transition_id": record.transition_id,
            "deployment_id": record.deployment_id,
            "source_phase": record.source_phase.value,
            "target_phase": record.target_phase.value,
            "activation_fingerprint": record.activation_fingerprint,
            "state_fingerprint": record.state_fingerprint,
            "truth_hash": record.truth_hash,
            "requested_risk": str(record.requested_risk),
            "effective_risk": str(record.effective_risk),
            "authorized_at": cls._iso(record.authorized_at),
            "status": record.status.value,
            "operator": record.operator,
            "decision_id": record.decision_id,
            "recorded_at_ms": record.recorded_at_ms,
            "valid_from": cls._iso(record.valid_from),
            "expires_at": cls._iso(record.expires_at),
            "state_chain_head": record.state_chain_head,
            "recovery_proof_id": record.recovery_proof_id,
            "recovery_proof_fingerprint": record.recovery_proof_fingerprint,
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> StateTransitionAuthorityRecord:
        try:
            record = StateTransitionAuthorityRecord(
                transition_id=str(payload["transition_id"]),
                deployment_id=str(payload["deployment_id"]),
                source_phase=DeploymentPhase(str(payload["source_phase"])),
                target_phase=DeploymentPhase(str(payload["target_phase"])),
                activation_fingerprint=str(payload["activation_fingerprint"]),
                state_fingerprint=str(payload["state_fingerprint"]),
                truth_hash=str(payload["truth_hash"]),
                requested_risk=Decimal(str(payload["requested_risk"])),
                effective_risk=Decimal(str(payload["effective_risk"])),
                authorized_at=datetime.fromisoformat(str(payload["authorized_at"])),
                status=TransitionStatus(str(payload["status"])),
                operator=str(payload["operator"]),
                decision_id=str(payload["decision_id"]),
                recorded_at_ms=int(payload["recorded_at_ms"]),
                valid_from=datetime.fromisoformat(str(payload["valid_from"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                state_chain_head=str(payload.get("state_chain_head", "")),
                recovery_proof_id=str(payload.get("recovery_proof_id", "")),
                recovery_proof_fingerprint=str(payload.get("recovery_proof_fingerprint", "")),
            )
        except Exception as exc:
            raise StateTransitionAuthorityInvalid("INVALID_TRANSITION_AUTHORIZATION_PAYLOAD") from exc
        if not record.transition_id or not record.deployment_id or not record.activation_fingerprint or not record.state_fingerprint or not record.truth_hash or not record.operator or not record.decision_id:
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_IDENTIFIERS_REQUIRED")
        if record.authorized_at.tzinfo is None or record.valid_from.tzinfo is None or record.expires_at.tzinfo is None:
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_TIMEZONE_REQUIRED")
        if record.expires_at <= record.valid_from:
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_WINDOW_INVALID")
        if record.requested_risk < 0 or record.effective_risk < 0 or not record.requested_risk.is_finite() or not record.effective_risk.is_finite():
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_RISK_INVALID")
        if record.recorded_at_ms < 0:
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_TIMESTAMP_INVALID")
        return record

    def authorize(self, record: StateTransitionAuthorityRecord) -> tuple[StateTransitionAuthorityRecord, bool]:
        if not self.store.verify_chain():
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_EVENT_CHAIN_INVALID")
        if record.source_phase is not DeploymentPhase.CANARY or record.target_phase is not DeploymentPhase.ACTIVATED:
            raise StateTransitionAuthorityInvalid("FINAL_ACTIVATION_TRANSITION_REQUIRED")
        payload = self.payload_from_record(record)
        event_id = f"deployment-transition:authorize:{record.transition_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED:
                raise StateTransitionAuthorityConflict("TRANSITION_EVENT_TYPE_CONFLICT")
            existing_record = self._from_payload(existing.payload)
            if self.fingerprint_from_payload(payload) != self.fingerprint_from_payload(self.payload_from_record(existing_record)):
                raise StateTransitionAuthorityConflict("TRANSITION_ID_CONFLICT")
            if not self.store.verify_chain():
                raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_EVENT_CHAIN_INVALID")
            return existing_record, False
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=record.recorded_at_ms,
                event_type=self.RECORDED,
                aggregate_id=record.deployment_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = self.store.get(event_id)
            if existing is None:
                raise StateTransitionAuthorityInvalid("TRANSITION_CONCURRENT_APPEND_UNRESOLVED") from exc
            existing_record = self._from_payload(existing.payload)
            if self.fingerprint_from_payload(payload) != self.fingerprint_from_payload(self.payload_from_record(existing_record)):
                raise StateTransitionAuthorityConflict("TRANSITION_CONCURRENT_CONFLICT") from exc
            return existing_record, False
        if not self.store.verify_chain():
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_EVENT_CHAIN_INVALID")
        return self._from_payload(result.event.payload), True

    def get(self, transition_id: str) -> StateTransitionAuthorityRecord | None:
        if not self.store.verify_chain():
            raise StateTransitionAuthorityInvalid("TRANSITION_AUTHORITY_EVENT_CHAIN_INVALID")
        event = self.store.get(f"deployment-transition:authorize:{transition_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise StateTransitionAuthorityInvalid("TRANSITION_EVENT_TYPE_MISMATCH")
        record = self._from_payload(event.payload)
        if record.transition_id != transition_id:
            raise StateTransitionAuthorityConflict("TRANSITION_ID_MISMATCH")
        return record


class DeploymentStateTransitionAuthority:
    """Machine-enforced final deployment state-transition authority.

    The V3.25 activation record is revalidated, then a durable transition
    authorization is recorded before the V3.28 transition primitive is called.
    The V3.28 primitive accepts the call only while the matching capability is
    installed in its protected authority context.
    """

    def __init__(self, *, activation_ledger: DeploymentActivationLedger, proof_ledger: RecoveryProofLedger,
                 transition_ledger: StateTransitionAuthorityLedger) -> None:
        self.activation_ledger = activation_ledger
        self.proof_ledger = proof_ledger
        self.transition_ledger = transition_ledger

    def authorize_final_activation(
        self,
        state: DeploymentState,
        *,
        now: datetime,
        now_ns: int,
        current_state_fingerprint: str,
        current_truth_hash: str,
        current_promotion_fingerprint: str,
        current_approval: Approval,
        operator: str,
        decision_id: str,
        transition_id: str,
    ) -> StateTransitionAuthorityRecord:
        if state.phase is not DeploymentPhase.CANARY:
            raise StateTransitionAuthorityInvalid("FINAL_ACTIVATION_SOURCE_MUST_BE_CANARY")
        activation = self.activation_ledger.assert_valid(
            state.request.deployment_id,
            now=now,
            current_state_fingerprint=current_state_fingerprint,
            current_truth_hash=current_truth_hash,
            current_promotion_fingerprint=current_promotion_fingerprint,
            current_approval=current_approval,
            proof_ledger=self.proof_ledger,
        )
        if activation.target_mode is not state.request.runtime_state.mode:
            raise StateTransitionAuthorityInvalid("TRANSITION_TARGET_MODE_MISMATCH")
        if activation.bundle_id != state.request.bundle.bundle_id:
            raise StateTransitionAuthorityConflict("TRANSITION_BUNDLE_MISMATCH")
        if activation.compatibility_authorization_id != state.request.compatibility_authorization_id:
            raise StateTransitionAuthorityConflict("TRANSITION_COMPATIBILITY_AUTHORITY_MISMATCH")
        if activation.approval_id != state.request.approval.approval_id:
            raise StateTransitionAuthorityConflict("TRANSITION_APPROVAL_MISMATCH")
        if state.request.runtime_state.mode is OperationalMode.LIVE and not activation.human_review_authorization_id:
            raise StateTransitionAuthorityInvalid("TRANSITION_HUMAN_REVIEW_REQUIRED")
        if activation.requested_risk != state.request.requested_risk:
            raise StateTransitionAuthorityConflict("TRANSITION_REQUESTED_RISK_MISMATCH")
        if state.allocated_risk > activation.effective_risk:
            raise StateTransitionAuthorityInvalid("TRANSITION_WOULD_INCREASE_AUTHORIZED_RISK")
        try:
            DownstreamDependencyAuthorityLedger(self.transition_ledger.store).authorize(
                authorization_id=f"deployment-transition:{transition_id}",
                artifact_id=transition_id,
                artifact_type="DEPLOYMENT_STATE_TRANSITION",
                dependencies=(
                    DependencyReference(
                        event_id=f"deployment-activation:authorize:{state.request.deployment_id}",
                        expected_event_type="DEPLOYMENT_ACTIVATION_AUTHORIZED",
                        expected_aggregate_id=state.request.deployment_id,
                    ),
                    DependencyReference(
                        event_id=activation.recovery_readiness_authorization_id and f"recovery-readiness:authorize:{activation.recovery_readiness_authorization_id}",
                        expected_event_type="RECOVERY_READINESS_AUTHORIZED",
                    ),
                    *((DependencyReference(
                        event_id=f"human-review:approve:{activation.human_review_authorization_id}",
                        expected_event_type="HUMAN_REVIEW_APPROVED",
                        expected_aggregate_id=activation.bundle_id,
                    ),) if activation.human_review_authorization_id else ()),
                ),
                now_ms=now_ns // 1_000_000,
            )
        except Exception as exc:
            raise StateTransitionAuthorityInvalid(f"DOWNSTREAM_DEPENDENCY_BLOCKED:{exc}") from exc
        record = StateTransitionAuthorityRecord(
            transition_id=transition_id,
            deployment_id=state.request.deployment_id,
            source_phase=state.phase,
            target_phase=DeploymentPhase.ACTIVATED,
            activation_fingerprint=activation.fingerprint,
            state_fingerprint=current_state_fingerprint,
            truth_hash=current_truth_hash,
            requested_risk=activation.requested_risk,
            effective_risk=activation.effective_risk,
            authorized_at=now.astimezone(timezone.utc),
            status=TransitionStatus.AUTHORIZED,
            operator=operator,
            decision_id=decision_id,
            recorded_at_ms=now_ns // 1_000_000 if now_ns >= 0 else -1,
            valid_from=activation.valid_from,
            expires_at=activation.expires_at,
            state_chain_head=state.chain.head_hash,
            recovery_proof_id=activation.proof_id,
            recovery_proof_fingerprint=activation.recovery_proof_fingerprint,
        )
        stored, _ = self.transition_ledger.authorize(record)
        return stored

    def activate(
        self,
        state: DeploymentState,
        *,
        now: datetime,
        now_ns: int,
        current_state_fingerprint: str,
        current_truth_hash: str,
        current_promotion_fingerprint: str,
        current_approval: Approval,
        operator: str,
        decision_id: str,
        transition_id: str,
        orchestrator: DeploymentOrchestrator,
    ) -> DeploymentState:
        auth = self.authorize_final_activation(
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
        capability = _issue_activation_capability(
            deployment_id=auth.deployment_id,
            activation_fingerprint=auth.activation_fingerprint,
            target_mode=state.request.runtime_state.mode.value,
            effective_risk=auth.effective_risk,
            valid_from=auth.valid_from,
            expires_at=auth.expires_at,
        )
        with activation_capability_context(capability):
            result = orchestrator.activate(state, now=now, now_ns=now_ns)
        if result.phase is not DeploymentPhase.ACTIVATED:
            raise StateTransitionAuthorityInvalid("FINAL_ACTIVATION_TARGET_NOT_COMMITTED")
        if result.allocated_risk > auth.effective_risk:
            raise StateTransitionAuthorityInvalid("FINAL_ACTIVATION_RISK_POSTCONDITION_FAILED")
        return result

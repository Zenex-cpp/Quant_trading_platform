from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json

from trading_platform.promotion.contracts import PromotionBundle, Approval, GateSummary, ScopeCheck, promotion_allowed
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState, assert_runtime_activation
from trading_platform.v28.deployment_authority import assert_activation_capability, consume_activation_capability
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityLedger, CompatibilityAuthorityError
from trading_platform.v342.artifact_integrity import ArtifactIntegrityAuthorityLedger, ArtifactIntegrityAuthorityError

class DeploymentPhase(str, Enum):
    IDLE = "IDLE"
    PREPARED = "PREPARED"
    STAGED = "STAGED"
    CANARY = "CANARY"
    ACTIVATED = "ACTIVATED"
    ABORTED = "ABORTED"
    ROLLED_BACK = "ROLLED_BACK"
    CLOSED = "CLOSED"

class DeploymentEventType(str, Enum):
    PREPARE = "PREPARE"
    STAGE = "STAGE"
    CANARY_START = "CANARY_START"
    CANARY_ABORT = "CANARY_ABORT"
    ACTIVATE = "ACTIVATE"
    ROLLBACK = "ROLLBACK"
    CLOSE = "CLOSE"

@dataclass(frozen=True)
class DeploymentEvent:
    sequence: int
    event_type: DeploymentEventType
    deployment_id: str
    actor: str
    from_phase: DeploymentPhase
    to_phase: DeploymentPhase
    risk_before: Decimal
    risk_after: Decimal
    reason: str
    timestamp_ns: int
    previous_hash: str
    event_hash: str

    @staticmethod
    def build(*, sequence: int, event_type: DeploymentEventType, deployment_id: str, actor: str,
              from_phase: DeploymentPhase, to_phase: DeploymentPhase, risk_before: Decimal,
              risk_after: Decimal, reason: str, timestamp_ns: int, previous_hash: str) -> "DeploymentEvent":
        payload = {
            "sequence": sequence, "event_type": event_type.value, "deployment_id": deployment_id,
            "actor": actor, "from_phase": from_phase.value, "to_phase": to_phase.value,
            "risk_before": str(risk_before), "risk_after": str(risk_after), "reason": reason,
            "timestamp_ns": timestamp_ns, "previous_hash": previous_hash,
        }
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return DeploymentEvent(sequence, event_type, deployment_id, actor, from_phase, to_phase,
                               risk_before, risk_after, reason, timestamp_ns, previous_hash, digest)

    def verify(self, previous_hash: str) -> bool:
        return self.previous_hash == previous_hash and self.event_hash == DeploymentEvent.build(
            sequence=self.sequence, event_type=self.event_type, deployment_id=self.deployment_id,
            actor=self.actor, from_phase=self.from_phase, to_phase=self.to_phase,
            risk_before=self.risk_before, risk_after=self.risk_after, reason=self.reason,
            timestamp_ns=self.timestamp_ns, previous_hash=self.previous_hash).event_hash

@dataclass(frozen=True)
class DeploymentAuditChain:
    events: tuple[DeploymentEvent, ...] = ()
    @property
    def head_hash(self) -> str:
        return self.events[-1].event_hash if self.events else "GENESIS"
    def append(self, event: DeploymentEvent) -> "DeploymentAuditChain":
        if event.sequence != len(self.events) + 1:
            raise ValueError("DEPLOYMENT_SEQUENCE_GAP")
        if not event.verify(self.head_hash):
            raise ValueError("DEPLOYMENT_EVENT_INVALID")
        return DeploymentAuditChain(self.events + (event,))
    def verify(self) -> None:
        previous = "GENESIS"
        for i, event in enumerate(self.events, 1):
            if event.sequence != i or not event.verify(previous):
                raise ValueError("DEPLOYMENT_CHAIN_INVALID")
            previous = event.event_hash

@dataclass(frozen=True)
class DeploymentRequest:
    deployment_id: str
    bundle: PromotionBundle
    approval: Approval
    gates: GateSummary
    scope: ScopeCheck
    evidence_valid: bool
    compatibility_valid: bool
    artifacts_integrity: bool
    operator: str
    requested_risk: Decimal
    canary_exposure: Decimal
    runtime_state: RuntimeBundleState
    compatibility_authorization_id: str | None = None
    artifact_integrity_authorization_id: str | None = None
    promotion_bundle_authorization_id: str | None = None

@dataclass(frozen=True)
class DeploymentState:
    request: DeploymentRequest
    phase: DeploymentPhase = DeploymentPhase.IDLE
    allocated_risk: Decimal = Decimal("0")
    chain: DeploymentAuditChain = DeploymentAuditChain()
    failure_reason: str | None = None

    @property
    def trading_allowed(self) -> bool:
        return self.phase is DeploymentPhase.ACTIVATED and self.allocated_risk > 0 and self.failure_reason is None

class DeploymentOrchestrator:
    def __init__(self, *, policy: RolloutPolicy, dependency_authority: DependencyInvalidationLedger):
        if dependency_authority is None:
            raise ValueError("DEPENDENCY_AUTHORITY_REQUIRED")
        self.policy = policy
        self.dependency_authority = dependency_authority
        self.compatibility_authority = CompatibilityAuthorityLedger(dependency_authority.store)
        self.artifact_integrity_authority = ArtifactIntegrityAuthorityLedger(dependency_authority.store)

    def _transition(self, state: DeploymentState, *, event_type: DeploymentEventType,
                    to_phase: DeploymentPhase, risk_after: Decimal, reason: str, now_ns: int) -> DeploymentState:
        if risk_after < 0:
            raise ValueError("NEGATIVE_DEPLOYMENT_RISK")
        event = DeploymentEvent.build(sequence=len(state.chain.events)+1, event_type=event_type,
                                      deployment_id=state.request.deployment_id, actor=state.request.operator,
                                      from_phase=state.phase, to_phase=to_phase,
                                      risk_before=state.allocated_risk, risk_after=risk_after,
                                      reason=reason, timestamp_ns=now_ns, previous_hash=state.chain.head_hash)
        return DeploymentState(state.request, to_phase, risk_after, state.chain.append(event), state.failure_reason)

    def prepare(self, request: DeploymentRequest, *, now: datetime, now_ns: int) -> DeploymentState:
        if request.requested_risk < 0 or request.canary_exposure < 0:
            raise ValueError("NEGATIVE_DEPLOYMENT_LIMIT")
        request.bundle.validate()
        if not request.promotion_bundle_authorization_id:
            raise ValueError("PROMOTION_BUNDLE_AUTHORITY_REQUIRED")
        if not request.compatibility_authorization_id:
            raise ValueError("COMPATIBILITY_AUTHORITY_REQUIRED")
        if not request.artifact_integrity_authorization_id:
            raise ValueError("ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED")
        try:
            self.compatibility_authority.assert_valid(
                request.compatibility_authorization_id,
                now=now,
                artifact_id=request.bundle.bundle_id,
                artifact_hashes=request.bundle.artifact_hashes,
                code_version=request.bundle.code_version,
                configuration_version=request.bundle.configuration_version,
                execution_model_version=request.bundle.execution_model_version,
                dependency_authority=self.dependency_authority,
            )
        except CompatibilityAuthorityError as exc:
            raise ValueError(f"COMPATIBILITY_AUTHORITY_BLOCKED:{exc}") from exc
        try:
            self.artifact_integrity_authority.assert_valid(
                request.artifact_integrity_authorization_id,
                now=now,
                artifact_id=request.bundle.bundle_id,
                artifact_hashes=request.bundle.artifact_hashes,
                dependency_authority=self.dependency_authority,
            )
        except ArtifactIntegrityAuthorityError as exc:
            raise ValueError(f"ARTIFACT_INTEGRITY_AUTHORITY_BLOCKED:{exc}") from exc
        if not request.artifacts_integrity:
            raise ValueError("ARTIFACT_INTEGRITY_BLOCKED")
        ok = promotion_allowed(bundle=request.bundle, gates=request.gates, approval=request.approval,
                               evidence_valid=request.evidence_valid, compatibility_valid=request.compatibility_valid,
                               scope=request.scope, artifacts_integrity=request.artifacts_integrity, now=now, dependency_authority=self.dependency_authority, promotion_bundle_authorization_id=request.promotion_bundle_authorization_id)
        if not ok:
            raise ValueError("DEPLOYMENT_GATE_BLOCKED")
        assert_runtime_activation(request.runtime_state, policy=self.policy, allocated_risk=Decimal("0"), exposure=Decimal("0"))
        return self._transition(DeploymentState(request), event_type=DeploymentEventType.PREPARE,
                                to_phase=DeploymentPhase.PREPARED, risk_after=Decimal("0"), reason="PREPARED", now_ns=now_ns)

    def stage(self, state: DeploymentState, *, now_ns: int) -> DeploymentState:
        if state.phase is not DeploymentPhase.PREPARED:
            raise ValueError("STAGE_REQUIRES_PREPARED")
        return self._transition(state, event_type=DeploymentEventType.STAGE, to_phase=DeploymentPhase.STAGED,
                                risk_after=Decimal("0"), reason="ARTIFACTS_STAGED", now_ns=now_ns)

    def start_canary(self, state: DeploymentState, *, now_ns: int) -> DeploymentState:
        if state.phase is not DeploymentPhase.STAGED:
            raise ValueError("CANARY_REQUIRES_STAGED")
        if self.policy.live_requires_canary:
            if state.request.requested_risk > self.policy.canary_max_risk_budget:
                raise ValueError("CANARY_RISK_CAP_BREACH")
            if state.request.canary_exposure > self.policy.canary_max_exposure:
                raise ValueError("CANARY_EXPOSURE_CAP_BREACH")
        canary_risk = min(state.request.requested_risk, self.policy.canary_max_risk_budget)
        return self._transition(state, event_type=DeploymentEventType.CANARY_START, to_phase=DeploymentPhase.CANARY,
                                risk_after=canary_risk, reason="CANARY_STARTED", now_ns=now_ns)

    def abort(self, state: DeploymentState, *, reason: str, now_ns: int) -> DeploymentState:
        if not reason:
            raise ValueError("ABORT_REASON_REQUIRED")
        if state.phase not in {DeploymentPhase.CANARY, DeploymentPhase.STAGED, DeploymentPhase.PREPARED}:
            raise ValueError("ABORT_PHASE_INVALID")
        out = self._transition(state, event_type=DeploymentEventType.CANARY_ABORT,
                               to_phase=DeploymentPhase.ABORTED, risk_after=Decimal("0"),
                               reason=reason, now_ns=now_ns)
        return DeploymentState(out.request, out.phase, Decimal("0"), out.chain, reason)

    def _activation_capability(self, state: DeploymentState, *, now: datetime):
        return assert_activation_capability(
            deployment_id=state.request.deployment_id,
            target_mode=state.request.runtime_state.mode.value,
            allocated_risk=state.allocated_risk,
            now=now,
        )

    def _validate_activation(self, state: DeploymentState, *, now: datetime) -> None:
        if state.phase is not DeploymentPhase.CANARY:
            raise ValueError("ACTIVATE_REQUIRES_CANARY")
        state.request.approval.validate(now)
        if state.request.runtime_state.health in {"FAILED", "FROZEN", "BLOCKED", "UNKNOWN"}:
            raise ValueError("ACTIVATION_HEALTH_BLOCKED")
        if not state.request.evidence_valid or not state.request.compatibility_valid or not state.request.artifacts_integrity:
            raise ValueError("ACTIVATION_EVIDENCE_BLOCKED")
        if not state.request.compatibility_authorization_id:
            raise ValueError("COMPATIBILITY_AUTHORITY_REQUIRED")
        if not state.request.artifact_integrity_authorization_id:
            raise ValueError("ARTIFACT_INTEGRITY_AUTHORITY_REQUIRED")
        try:
            self.compatibility_authority.assert_valid(
                state.request.compatibility_authorization_id,
                now=now,
                artifact_id=state.request.bundle.bundle_id,
                artifact_hashes=state.request.bundle.artifact_hashes,
                code_version=state.request.bundle.code_version,
                configuration_version=state.request.bundle.configuration_version,
                execution_model_version=state.request.bundle.execution_model_version,
                dependency_authority=self.dependency_authority,
            )
        except CompatibilityAuthorityError as exc:
            raise ValueError(f"COMPATIBILITY_AUTHORITY_BLOCKED:{exc}") from exc
        try:
            self.artifact_integrity_authority.assert_valid(
                state.request.artifact_integrity_authorization_id,
                now=now,
                artifact_id=state.request.bundle.bundle_id,
                artifact_hashes=state.request.bundle.artifact_hashes,
                dependency_authority=self.dependency_authority,
            )
        except ArtifactIntegrityAuthorityError as exc:
            raise ValueError(f"ARTIFACT_INTEGRITY_AUTHORITY_BLOCKED:{exc}") from exc
        if not state.request.artifacts_integrity:
            raise ValueError("ARTIFACT_INTEGRITY_BLOCKED")
        if state.request.requested_risk > self.policy.canary_max_risk_budget:
            raise ValueError("ACTIVATION_REQUIRES_EXPLICIT_CANARY_LIMIT")
        assert_runtime_activation(state.request.runtime_state, policy=self.policy,
                                  allocated_risk=state.allocated_risk, exposure=state.request.canary_exposure)

    def plan_activate(self, state: DeploymentState, *, now: datetime, now_ns: int) -> DeploymentState:
        # V3.28: pure deterministic planning. No capability consumption or mutable side effect.
        self._activation_capability(state, now=now)
        self._validate_activation(state, now=now)
        return self._transition(
            state, event_type=DeploymentEventType.ACTIVATE, to_phase=DeploymentPhase.ACTIVATED,
            risk_after=state.allocated_risk, reason="ACTIVATED_AFTER_CANARY", now_ns=now_ns
        )

    def activate(self, state: DeploymentState, *, now: datetime, now_ns: int) -> DeploymentState:
        capability = self._activation_capability(state, now=now)
        result = self.plan_activate(state, now=now, now_ns=now_ns)
        consume_activation_capability(capability)
        return result

    def rollback(self, state: DeploymentState, *, reason: str, now_ns: int) -> DeploymentState:
        if not reason:
            raise ValueError("ROLLBACK_REASON_REQUIRED")
        if state.phase not in {DeploymentPhase.ACTIVATED, DeploymentPhase.CANARY, DeploymentPhase.STAGED}:
            raise ValueError("ROLLBACK_PHASE_INVALID")
        out = self._transition(state, event_type=DeploymentEventType.ROLLBACK,
                               to_phase=DeploymentPhase.ROLLED_BACK, risk_after=Decimal("0"),
                               reason=reason, now_ns=now_ns)
        return DeploymentState(out.request, out.phase, Decimal("0"), out.chain, reason)

    def close(self, state: DeploymentState, *, now_ns: int) -> DeploymentState:
        if state.phase not in {DeploymentPhase.ABORTED, DeploymentPhase.ROLLED_BACK}:
            raise ValueError("CLOSE_REQUIRES_TERMINAL_PHASE")
        return self._transition(state, event_type=DeploymentEventType.CLOSE, to_phase=DeploymentPhase.CLOSED,
                                risk_after=Decimal("0"), reason="CLOSED", now_ns=now_ns)

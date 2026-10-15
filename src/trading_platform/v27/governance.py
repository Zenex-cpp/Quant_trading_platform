from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable

from trading_platform.v26.governance import ChampionChallengerRegistry, GovernedModel, GovernanceStatus, invalidate_promotion
from trading_platform.promotion.contracts import ModelRole, OperationalMode, DeploymentState

class GovernanceEventType(str, Enum):
    PROMOTION = "PROMOTION"
    DEMOTION = "DEMOTION"
    QUARANTINE = "QUARANTINE"
    ROLLBACK = "ROLLBACK"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"

@dataclass(frozen=True)
class GovernanceEvent:
    event_id: str
    sequence: int
    event_type: GovernanceEventType
    actor: str
    model_id: str
    previous_model_id: str | None
    reason: str
    risk_before: Decimal
    risk_after: Decimal
    timestamp_ns: int
    previous_hash: str
    event_hash: str

    @staticmethod
    def build(*, sequence: int, event_type: GovernanceEventType, actor: str, model_id: str,
              previous_model_id: str | None, reason: str, risk_before: Decimal,
              risk_after: Decimal, timestamp_ns: int, previous_hash: str = "GENESIS") -> "GovernanceEvent":
        payload = {
            "sequence": sequence, "event_type": event_type.value, "actor": actor,
            "model_id": model_id, "previous_model_id": previous_model_id, "reason": reason,
            "risk_before": str(risk_before), "risk_after": str(risk_after),
            "timestamp_ns": timestamp_ns, "previous_hash": previous_hash,
        }
        event_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return GovernanceEvent(sha256(event_hash.encode()).hexdigest()[:24], sequence, event_type, actor,
                               model_id, previous_model_id, reason, risk_before, risk_after,
                               timestamp_ns, previous_hash, event_hash)

    def verify(self, expected_previous_hash: str) -> bool:
        return self.previous_hash == expected_previous_hash and self.event_hash == GovernanceEvent.build(
            sequence=self.sequence, event_type=self.event_type, actor=self.actor,
            model_id=self.model_id, previous_model_id=self.previous_model_id, reason=self.reason,
            risk_before=self.risk_before, risk_after=self.risk_after, timestamp_ns=self.timestamp_ns,
            previous_hash=self.previous_hash).event_hash

@dataclass(frozen=True)
class GovernanceChain:
    events: tuple[GovernanceEvent, ...] = ()

    @property
    def head_hash(self) -> str:
        return self.events[-1].event_hash if self.events else "GENESIS"

    def append(self, event: GovernanceEvent) -> "GovernanceChain":
        if event.sequence != len(self.events) + 1:
            raise ValueError("GOVERNANCE_SEQUENCE_GAP")
        if not event.verify(self.head_hash):
            raise ValueError("GOVERNANCE_EVENT_INVALID")
        return GovernanceChain(self.events + (event,))

    def verify(self) -> None:
        previous = "GENESIS"
        for idx, event in enumerate(self.events, start=1):
            if event.sequence != idx or not event.verify(previous):
                raise ValueError("GOVERNANCE_CHAIN_INVALID")
            previous = event.event_hash

@dataclass(frozen=True)
class RollbackRecord:
    rollback_id: str
    from_model_id: str
    to_model_id: str
    reason: str
    actor: str
    timestamp_ns: int
    pre_state_hash: str
    post_state_hash: str
    event_hash: str

@dataclass(frozen=True)
class GovernanceController:
    registry: ChampionChallengerRegistry
    chain: GovernanceChain = GovernanceChain()
    def _state_hash(self, registry: ChampionChallengerRegistry) -> str:
        payload = []
        for m in sorted(registry.models, key=lambda x: x.model_id):
            payload.append({"model_id": m.model_id, "version": m.version, "role": m.role.value,
                            "mode": m.mode.value, "deployment": m.deployment.value, "health": m.health.value,
                            "governance": m.governance.value, "evidence_valid": m.evidence_valid,
                            "approval_valid": m.approval_valid, "risk": str(m.effective_risk_budget),
                            "reason": m.invalidation_reason})
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def promote(self, challenger_id: str, *, actor: str, validated: bool, now_ns: int, gate_authorization=None, evidence_snapshot_authorization=None, promotion_bundle_authorization_id=None, dependency_authority=None, now=None) -> "GovernanceController":
        old = self.registry
        old_champion = old.champion()
        if old_champion is None:
            raise ValueError("CHAMPION_REQUIRED")
        new = old.promote(challenger_id, validated=validated, gate_authorization=gate_authorization, evidence_snapshot_authorization=evidence_snapshot_authorization, promotion_bundle_authorization_id=promotion_bundle_authorization_id, dependency_authority=dependency_authority, now=now)
        new_champion = new.champion()
        event = GovernanceEvent.build(sequence=len(self.chain.events)+1, event_type=GovernanceEventType.PROMOTION,
                                      actor=actor, model_id=challenger_id,
                                      previous_model_id=old_champion.model_id, reason="PROMOTION_VALIDATED",
                                      risk_before=old_champion.effective_risk_budget,
                                      risk_after=new_champion.effective_risk_budget, timestamp_ns=now_ns,
                                      previous_hash=self.chain.head_hash)
        return GovernanceController(new, self.chain.append(event))

    def quarantine(self, model_id: str, *, actor: str, reason: str, now_ns: int) -> "GovernanceController":
        old = self.registry
        model = next((m for m in old.models if m.model_id == model_id), None)
        if model is None: raise ValueError("MODEL_NOT_FOUND")
        new = old.quarantine(model_id, reason=reason)
        event = GovernanceEvent.build(sequence=len(self.chain.events)+1, event_type=GovernanceEventType.QUARANTINE,
                                      actor=actor, model_id=model_id, previous_model_id=old.champion().model_id if old.champion() else None,
                                      reason=reason, risk_before=model.effective_risk_budget, risk_after=Decimal("0"),
                                      timestamp_ns=now_ns, previous_hash=self.chain.head_hash)
        return GovernanceController(new, self.chain.append(event))

    def rollback(self, target_model_id: str, *, actor: str, reason: str, now_ns: int) -> tuple["GovernanceController", RollbackRecord]:
        if not reason: raise ValueError("ROLLBACK_REASON_REQUIRED")
        current = self.registry.champion()
        target = next((m for m in self.registry.models if m.model_id == target_model_id), None)
        if current is None: raise ValueError("CHAMPION_REQUIRED")
        if target is None: raise ValueError("ROLLBACK_TARGET_NOT_FOUND")
        if target.model_id == current.model_id: raise ValueError("ROLLBACK_TARGET_IS_CURRENT")
        if target.governance in {GovernanceStatus.QUARANTINED, GovernanceStatus.BLOCKED}: raise ValueError("ROLLBACK_TARGET_UNSAFE")
        if target.health.value != "HEALTHY" or not target.evidence_valid or not target.approval_valid: raise ValueError("ROLLBACK_TARGET_NOT_ELIGIBLE")
        if target.role not in {ModelRole.CHALLENGER, ModelRole.CHAMPION}: raise ValueError("ROLLBACK_ROLE_INVALID")
        historical_target_risk = target.effective_risk_budget
        for evt in reversed(self.chain.events):
            if evt.event_type is GovernanceEventType.PROMOTION and evt.previous_model_id == target.model_id:
                historical_target_risk = evt.risk_before
                break
        out=[]
        for m in self.registry.models:
            if m.model_id == target.model_id:
                out.append(GovernedModel(m.model_id,m.version,ModelRole.CHAMPION,OperationalMode.LIVE,DeploymentState.ACTIVE,m.health,GovernanceStatus.ELIGIBLE,m.evidence_valid,m.approval_valid,historical_target_risk))
            elif m.model_id == current.model_id:
                out.append(GovernedModel(m.model_id,m.version,ModelRole.CHALLENGER,OperationalMode.SHADOW,DeploymentState.ACTIVE,m.health,m.governance,m.evidence_valid,m.approval_valid,Decimal("0")))
            else:
                out.append(m)
        new_reg = ChampionChallengerRegistry(tuple(out))
        pre_hash = self._state_hash(self.registry)
        post_hash = self._state_hash(new_reg)
        event = GovernanceEvent.build(sequence=len(self.chain.events)+1, event_type=GovernanceEventType.ROLLBACK,
                                      actor=actor, model_id=target.model_id, previous_model_id=current.model_id,
                                      reason=reason, risk_before=current.effective_risk_budget,
                                      risk_after=target.effective_risk_budget, timestamp_ns=now_ns,
                                      previous_hash=self.chain.head_hash)
        new_chain = self.chain.append(event)
        rb = RollbackRecord(event.event_id, current.model_id, target.model_id, reason, actor, now_ns, pre_hash, post_hash, event.event_hash)
        return GovernanceController(new_reg, new_chain), rb

    def audit(self) -> None:
        self.chain.verify()
        if self.registry.champion() is not None and sum(1 for m in self.registry.models if m.role is ModelRole.CHAMPION and m.governance not in {GovernanceStatus.QUARANTINED, GovernanceStatus.BLOCKED}) > 1:
            raise ValueError("MULTIPLE_ACTIVE_CHAMPIONS")

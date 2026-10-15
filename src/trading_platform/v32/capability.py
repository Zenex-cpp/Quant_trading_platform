from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from trading_platform.v25.health import HealthAssessment
from trading_platform.v30.truth import CanonicalAction, OperationalTruth
from trading_platform.v31.authority import AuthorityDecision, AuthorityStatus, RuntimeAuthority

class CapabilityError(PermissionError):
    pass

@dataclass(frozen=True)
class TradeCapability:
    capability_id: str
    authority: AuthorityDecision
    intent_fingerprint: str
    expires_at: datetime
    consumed: bool = False
    model_health_assessment: HealthAssessment | None = None

    @property
    def truth_hash(self) -> str:
        return self.authority.truth_hash

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

class CapabilityAuthority:
    """Issues one-shot capabilities bound to exact intent inputs and truth hash."""
    def __init__(self, authority: RuntimeAuthority | None = None):
        self.authority = authority or RuntimeAuthority()
        self._consumed: set[str] = set()

    def issue(self, *, truth: OperationalTruth, requested_risk: Decimal, decision_id: str,
              intent_payload: dict[str, Any], expires_at: datetime,
              uncertainty: Decimal | None = None, max_uncertainty: Decimal = Decimal("1"),
              uncertainty_floor: Decimal = Decimal("0"),
              uncertainty_method: str = "CONSERVATIVE_LINEAR",
              uncertainty_method_version: str = "1",
              drawdown: Decimal | None = None, max_drawdown: Decimal = Decimal("1"),
              drawdown_floor: Decimal = Decimal("0"), drawdown_method: str = "CONSERVATIVE_LINEAR",
              drawdown_method_version: str = "1",
              model_health: Decimal | None = None, max_model_health: Decimal = Decimal("1"),
              model_health_floor: Decimal = Decimal("0"), model_health_method: str = "CONSERVATIVE_LINEAR",
              model_health_method_version: str = "1", model_health_assessment: HealthAssessment | None = None,
              model_health_assessment_id: str | None = None) -> TradeCapability:
        decision = self.authority.evaluate(
            truth=truth, action=CanonicalAction.TRADE, requested_risk=requested_risk,
            decision_id=decision_id, input_payload=intent_payload,
            uncertainty=uncertainty, max_uncertainty=max_uncertainty,
            uncertainty_floor=uncertainty_floor, uncertainty_method=uncertainty_method,
            uncertainty_method_version=uncertainty_method_version,
            drawdown=drawdown, max_drawdown=max_drawdown, drawdown_floor=drawdown_floor,
            drawdown_method=drawdown_method, drawdown_method_version=drawdown_method_version,
            model_health=model_health, max_model_health=max_model_health, model_health_floor=model_health_floor,
            model_health_method=model_health_method, model_health_method_version=model_health_method_version,
            model_health_assessment=model_health_assessment, model_health_assessment_id=model_health_assessment_id,
        )
        if not decision.authorized:
            raise CapabilityError(decision.reason)
        fp = TradeCapability.fingerprint({"intent": intent_payload, "truth_hash": truth.state_hash,
                                          "requested_risk": str(requested_risk),
                                          "uncertainty": None if uncertainty is None else str(uncertainty),
                                          "max_uncertainty": str(max_uncertainty),
                                          "uncertainty_floor": str(uncertainty_floor),
                                          "uncertainty_method": uncertainty_method,
                                          "uncertainty_method_version": uncertainty_method_version,
                                          "drawdown": None if drawdown is None else str(drawdown),
                                          "max_drawdown": str(max_drawdown),
                                          "drawdown_floor": str(drawdown_floor),
                                          "drawdown_method": drawdown_method,
                                          "drawdown_method_version": drawdown_method_version,
                                          "model_health": None if model_health is None else str(model_health),
                                          "max_model_health": str(max_model_health),
                                          "model_health_floor": str(model_health_floor),
                                          "model_health_method": model_health_method,
                                          "model_health_method_version": model_health_method_version,
                                          "model_health_assessment_id": model_health_assessment_id})
        cap_id = f"cap:{decision.decision_id}:{fp[:24]}"
        return TradeCapability(cap_id, decision, TradeCapability.fingerprint(intent_payload), expires_at, False, model_health_assessment)

    def validate(self, capability: TradeCapability, *, now: datetime, truth: OperationalTruth,
                 intent_payload: dict[str, Any], model_health: Decimal | None = None,
                 model_health_assessment: HealthAssessment | None = None,
                 model_health_assessment_id: str | None = None) -> None:
        if capability.capability_id in self._consumed or capability.consumed:
            raise CapabilityError("CAPABILITY_ALREADY_CONSUMED")
        if now >= capability.expires_at:
            raise CapabilityError("CAPABILITY_EXPIRED")
        if truth.state_hash != capability.truth_hash:
            raise CapabilityError("TRUTH_HASH_CHANGED")
        if not truth.decision_fresh or not truth.trading_allowed:
            raise CapabilityError("TRUTH_NO_LONGER_AUTHORIZES_TRADE")
        if capability.authority.model_health is not None:
            if model_health is None or model_health_assessment is None or not model_health_assessment_id:
                raise CapabilityError("MODEL_HEALTH_REVALIDATION_REQUIRED")
            if model_health != capability.authority.model_health:
                raise CapabilityError("MODEL_HEALTH_CHANGED")
            if model_health_assessment_id != capability.authority.model_health_assessment_id:
                raise CapabilityError("MODEL_HEALTH_ASSESSMENT_CHANGED")
            if model_health_assessment != capability.model_health_assessment:
                raise CapabilityError("MODEL_HEALTH_SOURCE_CHANGED")
        elif model_health is not None or model_health_assessment is not None or model_health_assessment_id is not None:
            raise CapabilityError("MODEL_HEALTH_UNEXPECTED_PROVENANCE")
        if TradeCapability.fingerprint(intent_payload) != capability.intent_fingerprint:
            raise CapabilityError("INTENT_FINGERPRINT_MISMATCH")

    def consume(self, capability: TradeCapability, *, now: datetime, truth: OperationalTruth,
                intent_payload: dict[str, Any], model_health: Decimal | None = None,
                model_health_assessment: HealthAssessment | None = None,
                model_health_assessment_id: str | None = None) -> TradeCapability:
        self.validate(capability, now=now, truth=truth, intent_payload=intent_payload,
                      model_health=model_health, model_health_assessment=model_health_assessment,
                      model_health_assessment_id=model_health_assessment_id)
        self._consumed.add(capability.capability_id)
        return TradeCapability(capability.capability_id, capability.authority, capability.intent_fingerprint,
                               capability.expires_at, consumed=True, model_health_assessment=capability.model_health_assessment)

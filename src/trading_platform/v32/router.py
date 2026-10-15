from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_platform.v30.truth import OperationalTruth
from trading_platform.v31.router import ExecutionRouter, AuthorizedOrderRequest
from trading_platform.execution.models import OrderIntent, PositionState
from trading_platform.core.ttl import ValidWindow
from trading_platform.v32.capability import CapabilityAuthority, TradeCapability

@dataclass(frozen=True)
class CommittedOrder:
    capability: TradeCapability
    authorized_request: AuthorizedOrderRequest

class CommitRouter:
    """Closes TOCTOU between authorization and dispatch by consuming a one-shot capability."""
    def __init__(self, *, capability_authority: CapabilityAuthority | None = None,
                 execution_router: ExecutionRouter | None = None):
        self.capabilities = capability_authority or CapabilityAuthority()
        self.router = execution_router or ExecutionRouter(authority=self.capabilities.authority)

    def commit(self, *, capability: TradeCapability, intent: OrderIntent, truth: OperationalTruth,
               now: datetime, position_state: PositionState, market_window: ValidWindow,
               upstream_windows: list[ValidWindow], risk_valid: bool, model_health: Decimal | None = None,
               model_health_assessment: HealthAssessment | None = None, model_health_assessment_id: str | None = None) -> CommittedOrder:
        payload = {
            "intent_id": intent.intent_id, "decision_id": intent.decision_id,
            "risk_decision_id": intent.risk_decision_id, "symbol": intent.symbol,
            "side": intent.side.value, "action": intent.action.value, "quantity": str(intent.quantity),
            "order_type": intent.order_type.value, "price": str(intent.price) if intent.price is not None else None,
            "execution_version": intent.execution_version,
        }
        if model_health is None and capability.authority.model_health is not None:
            model_health = capability.authority.model_health
        if model_health_assessment is None and capability.model_health_assessment is not None:
            model_health_assessment = capability.model_health_assessment
        if model_health_assessment_id is None and capability.authority.model_health_assessment_id is not None:
            model_health_assessment_id = capability.authority.model_health_assessment_id
        consumed = self.capabilities.consume(capability, now=now, truth=truth, intent_payload=payload,
                                             model_health=model_health, model_health_assessment=model_health_assessment,
                                             model_health_assessment_id=model_health_assessment_id)
        out = self.router.route(intent=intent, truth=truth, now=now, position_state=position_state,
                                market_window=market_window, upstream_windows=upstream_windows,
                                risk_valid=risk_valid, requested_risk=capability.authority.requested_risk,
                                decision_id=capability.authority.decision_id, input_payload=payload,
                                model_health=capability.authority.model_health,
                                model_health_method=capability.authority.model_health_method or "CONSERVATIVE_LINEAR",
                                model_health_method_version=capability.authority.model_health_method_version or "1",
                                model_health_assessment_id=capability.authority.model_health_assessment_id,
                                model_health_assessment=capability.model_health_assessment)
        return CommittedOrder(consumed, out)

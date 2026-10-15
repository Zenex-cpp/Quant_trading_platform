from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_platform.v25.health import HealthAssessment
from trading_platform.v30.truth import CanonicalAction, OperationalTruth
from trading_platform.v31.authority import RuntimeAuthority, AuthorityDecision
from trading_platform.execution.guards import build_order_request
from trading_platform.execution.models import OrderIntent, OrderRequest, PositionState
from trading_platform.core.ttl import ValidWindow

@dataclass(frozen=True)
class AuthorizedOrderRequest:
    authority: AuthorityDecision
    request: OrderRequest

    @property
    def order_request_id(self) -> str:
        return self.request.order_request_id

class ExecutionRouter:
    """Execution boundary requiring Operational Truth authorization."""
    def __init__(self, *, authority: RuntimeAuthority | None = None):
        self.authority = authority or RuntimeAuthority()

    def route(self, *, intent: OrderIntent, truth: OperationalTruth, now: datetime,
              position_state: PositionState, market_window: ValidWindow,
              upstream_windows: list[ValidWindow], risk_valid: bool,
              requested_risk: Decimal, decision_id: str,
              input_payload: dict[str, Any] | None = None,
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
              model_health_assessment_id: str | None = None) -> AuthorizedOrderRequest:
        decision = self.authority.evaluate(
            truth=truth, action=CanonicalAction.TRADE, requested_risk=requested_risk,
            decision_id=decision_id, input_payload=input_payload,
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
            raise PermissionError(decision.reason)
        request = build_order_request(
            intent, now=now, position_state=position_state, market_window=market_window,
            upstream_windows=upstream_windows, risk_valid=risk_valid,
        )
        return AuthorizedOrderRequest(authority=decision, request=request)

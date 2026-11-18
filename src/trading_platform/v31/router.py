from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from trading_platform.v25.health import HealthAssessment
from trading_platform.v349.liquidity_assessment import LiquidityAssessment
from trading_platform.v350.drawdown_history import DrawdownAssessment
from trading_platform.v348.uncertainty_assessment import UncertaintyAssessment
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
              uncertainty_assessment: UncertaintyAssessment | None = None,
              liquidity_stress: Decimal | None = None, max_liquidity_stress: Decimal = Decimal("1"),
              liquidity_floor: Decimal = Decimal("0"), liquidity_method: str = "CONSERVATIVE_LINEAR",
              liquidity_method_version: str = "1", liquidity_assessment: LiquidityAssessment | None = None,
              drawdown: Decimal | None = None, max_drawdown: Decimal = Decimal("1"),
              drawdown_floor: Decimal = Decimal("0"), drawdown_method: str = "CONSERVATIVE_LINEAR",
              drawdown_method_version: str = "1", drawdown_assessment: DrawdownAssessment | None = None,
              model_health: Decimal | None = None, max_model_health: Decimal = Decimal("1"),
              model_health_floor: Decimal = Decimal("0"), model_health_method: str = "CONSERVATIVE_LINEAR",
              model_health_method_version: str = "1", model_health_assessment: HealthAssessment | None = None,
              model_health_assessment_id: str | None = None) -> AuthorizedOrderRequest:
        if liquidity_assessment is not None:
            if not liquidity_assessment.matches_order(
                symbol=intent.symbol, side=intent.side, quantity=intent.quantity,
            ):
                raise PermissionError("LIQUIDITY_INTENT_MISMATCH")
            if not liquidity_assessment.source_fresh_at(self._datetime_to_epoch_ns(now)):
                raise PermissionError("LIQUIDITY_SOURCE_EXPIRED")
        if drawdown_assessment is not None and not drawdown_assessment.source_fresh_at(self._datetime_to_epoch_ns(now)):
            raise PermissionError("DRAWDOWN_SOURCE_EXPIRED")
        if uncertainty_assessment is not None and not uncertainty_assessment.source_fresh_at(self._datetime_to_epoch_ns(now)):
            raise PermissionError("UNCERTAINTY_SOURCE_EXPIRED")
        decision = self.authority.evaluate(
            truth=truth, action=CanonicalAction.TRADE, requested_risk=requested_risk,
            decision_id=decision_id, input_payload=input_payload,
            uncertainty=uncertainty, max_uncertainty=max_uncertainty,
            uncertainty_floor=uncertainty_floor, uncertainty_method=uncertainty_method,
            uncertainty_method_version=uncertainty_method_version,
            uncertainty_assessment=uncertainty_assessment,
            liquidity_stress=liquidity_stress, max_liquidity_stress=max_liquidity_stress,
            liquidity_floor=liquidity_floor, liquidity_method=liquidity_method,
            liquidity_method_version=liquidity_method_version,
            liquidity_assessment=liquidity_assessment,
            drawdown=drawdown, max_drawdown=max_drawdown, drawdown_floor=drawdown_floor,
            drawdown_method=drawdown_method, drawdown_method_version=drawdown_method_version,
            drawdown_assessment=drawdown_assessment,
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

    @staticmethod
    def _datetime_to_epoch_ns(value: datetime) -> int:
        if value.tzinfo is None or value.utcoffset() is None:
            raise PermissionError("DRAWDOWN_REVALIDATION_TIMEZONE_REQUIRED")
        utc_value = value.astimezone(timezone.utc)
        delta = utc_value - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return ((delta.days * 86400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1_000

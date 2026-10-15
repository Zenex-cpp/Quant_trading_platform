from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from trading_platform.v25.health import HealthAssessment
from trading_platform.v30.truth import CanonicalAction, OperationalTruth, TruthStatus, ConfigurationStatus
from trading_platform.v348.uncertainty_risk_authority import bind_uncertainty_to_risk, UncertaintyRiskError
from trading_platform.v349.liquidity_risk_authority import bind_liquidity_to_risk, LiquidityRiskError
from trading_platform.v350.drawdown_risk_authority import bind_drawdown_to_risk, DrawdownRiskError
from trading_platform.v351.model_health_risk_authority import bind_model_health_to_risk, ModelHealthRiskError
from trading_platform.v356.risk_state_monotonicity import (
    RiskStateMonotonicityError,
    conservative_state_risk_factor,
    state_severity,
    RiskStateRecoveryEventRecord,
)


class AuthorityStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"


@dataclass(frozen=True)
class AuthorityDecision:
    decision_id: str
    action: CanonicalAction
    status: AuthorityStatus
    reason: str
    truth_hash: str
    effective_risk: Decimal
    requested_risk: Decimal
    observed_at_ns: int
    input_fingerprint: str
    uncertainty: Decimal | None = None
    uncertainty_risk_factor: Decimal | None = None
    uncertainty_method: str | None = None
    uncertainty_method_version: str | None = None
    liquidity_stress: Decimal | None = None
    liquidity_risk_factor: Decimal | None = None
    liquidity_method: str | None = None
    liquidity_method_version: str | None = None
    drawdown: Decimal | None = None
    drawdown_risk_factor: Decimal | None = None
    drawdown_method: str | None = None
    drawdown_method_version: str | None = None
    model_health: Decimal | None = None
    model_health_risk_factor: Decimal | None = None
    model_health_method: str | None = None
    model_health_method_version: str | None = None
    model_health_assessment_id: str | None = None
    model_health_assessment: HealthAssessment | None = None
    risk_state: str = "NORMAL"
    risk_state_risk_factor: Decimal = Decimal("1")
    recovery_event_id: str | None = None

    @property
    def authorized(self) -> bool:
        return self.status is AuthorityStatus.AUTHORIZED

    @staticmethod
    def _fingerprint(payload: dict[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    @classmethod
    def build(
        cls,
        *,
        action: CanonicalAction,
        truth: OperationalTruth,
        status: AuthorityStatus,
        reason: str,
        requested_risk: Decimal,
        decision_id: str,
        input_payload: dict[str, Any] | None = None,
        uncertainty: Decimal | None = None,
        uncertainty_risk_factor: Decimal | None = None,
        uncertainty_method: str | None = None,
        uncertainty_method_version: str | None = None,
        liquidity_stress: Decimal | None = None,
        liquidity_risk_factor: Decimal | None = None,
        liquidity_method: str | None = None,
        liquidity_method_version: str | None = None,
        drawdown: Decimal | None = None,
        drawdown_risk_factor: Decimal | None = None,
        drawdown_method: str | None = None,
        drawdown_method_version: str | None = None,
        model_health: Decimal | None = None,
        model_health_risk_factor: Decimal | None = None,
        model_health_method: str | None = None,
        model_health_method_version: str | None = None,
        model_health_assessment_id: str | None = None,
        model_health_assessment: HealthAssessment | None = None,
        risk_state_risk_factor: Decimal = Decimal("1"),
        recovery_event_id: str | None = None,
    ) -> "AuthorityDecision":
        fp_payload = {
            "action": action.value,
            "truth_hash": truth.state_hash,
            "requested_risk": str(requested_risk),
            "payload": input_payload or {},
        }
        if truth.risk_state != "NORMAL" or risk_state_risk_factor != Decimal("1") or recovery_event_id is not None:
            fp_payload.update({
                "risk_state": truth.risk_state,
                "risk_state_risk_factor": str(risk_state_risk_factor),
                "recovery_event_id": recovery_event_id,
            })
        if uncertainty is not None:
            fp_payload.update({
                "uncertainty": str(uncertainty),
                "uncertainty_risk_factor": None if uncertainty_risk_factor is None else str(uncertainty_risk_factor),
                "uncertainty_method": uncertainty_method,
                "uncertainty_method_version": uncertainty_method_version,
            })
        if liquidity_stress is not None:
            fp_payload.update({
                "liquidity_stress": str(liquidity_stress),
                "liquidity_risk_factor": None if liquidity_risk_factor is None else str(liquidity_risk_factor),
                "liquidity_method": liquidity_method,
                "liquidity_method_version": liquidity_method_version,
            })
        if drawdown is not None:
            fp_payload.update({
                "drawdown": str(drawdown),
                "drawdown_risk_factor": None if drawdown_risk_factor is None else str(drawdown_risk_factor),
                "drawdown_method": drawdown_method,
                "drawdown_method_version": drawdown_method_version,
            })
        if model_health is not None:
            fp_payload.update({
                "model_health": str(model_health),
                "model_health_risk_factor": None if model_health_risk_factor is None else str(model_health_risk_factor),
                "model_health_method": model_health_method,
                "model_health_method_version": model_health_method_version,
                "model_health_assessment_id": model_health_assessment_id,
                "model_health_assessment_state": None if model_health_assessment is None else model_health_assessment.state.value,
                "model_health_assessment_evidence_fresh": None if model_health_assessment is None else model_health_assessment.evidence_fresh,
                "model_health_assessment_drift_critical": None if model_health_assessment is None else model_health_assessment.drift_critical,
                "model_health_assessment_quality_ok": None if model_health_assessment is None else model_health_assessment.quality_ok,
            })
        fp = cls._fingerprint(fp_payload)
        return cls(
            decision_id=decision_id,
            action=action,
            status=status,
            reason=reason,
            truth_hash=truth.state_hash,
            effective_risk=truth.effective_risk,
            requested_risk=requested_risk,
            observed_at_ns=truth.observed_at_ns,
            input_fingerprint=fp,
            uncertainty=uncertainty,
            uncertainty_risk_factor=uncertainty_risk_factor,
            uncertainty_method=uncertainty_method,
            uncertainty_method_version=uncertainty_method_version,
            liquidity_stress=liquidity_stress,
            liquidity_risk_factor=liquidity_risk_factor,
            liquidity_method=liquidity_method,
            liquidity_method_version=liquidity_method_version,
            drawdown=drawdown,
            drawdown_risk_factor=drawdown_risk_factor,
            drawdown_method=drawdown_method,
            drawdown_method_version=drawdown_method_version,
            model_health=model_health,
            model_health_risk_factor=model_health_risk_factor,
            model_health_method=model_health_method,
            model_health_method_version=model_health_method_version,
            model_health_assessment_id=model_health_assessment_id,
            model_health_assessment=model_health_assessment,
            risk_state=str(truth.risk_state),
            risk_state_risk_factor=Decimal(str(risk_state_risk_factor)),
            recovery_event_id=recovery_event_id,
        )


class RuntimeAuthority:
    """Single decision boundary for risk-taking actions."""

    def __init__(self, *, require_verified_for_trade: bool = True):
        self.require_verified_for_trade = require_verified_for_trade

    def evaluate(
        self,
        *,
        truth: OperationalTruth,
        action: CanonicalAction,
        requested_risk: Decimal = Decimal("0"),
        decision_id: str,
        input_payload: dict[str, Any] | None = None,
        uncertainty: Decimal | None = None,
        max_uncertainty: Decimal = Decimal("1"),
        uncertainty_floor: Decimal = Decimal("0"),
        uncertainty_method: str = "CONSERVATIVE_LINEAR",
        uncertainty_method_version: str = "1",
        liquidity_stress: Decimal | None = None,
        max_liquidity_stress: Decimal = Decimal("1"),
        liquidity_floor: Decimal = Decimal("0"),
        liquidity_method: str = "CONSERVATIVE_LINEAR",
        liquidity_method_version: str = "1",
        drawdown: Decimal | None = None,
        max_drawdown: Decimal = Decimal("1"),
        drawdown_floor: Decimal = Decimal("0"),
        drawdown_method: str = "CONSERVATIVE_LINEAR",
        drawdown_method_version: str = "1",
        model_health: Decimal | None = None,
        max_model_health: Decimal = Decimal("1"),
        model_health_floor: Decimal = Decimal("0"),
        model_health_method: str = "CONSERVATIVE_LINEAR",
        model_health_method_version: str = "1",
        model_health_assessment: HealthAssessment | None = None,
        model_health_assessment_id: str | None = None,
        recovery_event: RiskStateRecoveryEventRecord | None = None,
    ) -> AuthorityDecision:
        uncertainty_binding = None
        liquidity_binding = None
        drawdown_binding = None
        model_health_binding = None
        state_factor = Decimal("1")
        state_cap = truth.effective_risk

        def build(reason: str, status: AuthorityStatus) -> AuthorityDecision:
            return AuthorityDecision.build(
                action=action,
                truth=truth,
                status=status,
                reason=reason,
                requested_risk=requested_risk,
                decision_id=decision_id,
                input_payload=input_payload,
                uncertainty=uncertainty,
                uncertainty_risk_factor=None if uncertainty_binding is None else uncertainty_binding.risk_factor,
                uncertainty_method=None if uncertainty_binding is None else uncertainty_binding.method,
                uncertainty_method_version=None if uncertainty_binding is None else uncertainty_binding.method_version,
                liquidity_stress=liquidity_stress,
                liquidity_risk_factor=None if liquidity_binding is None else liquidity_binding.risk_factor,
                liquidity_method=None if liquidity_binding is None else liquidity_binding.method,
                liquidity_method_version=None if liquidity_binding is None else liquidity_binding.method_version,
                drawdown=drawdown,
                drawdown_risk_factor=None if drawdown_binding is None else drawdown_binding.risk_factor,
                drawdown_method=None if drawdown_binding is None else drawdown_binding.method,
                drawdown_method_version=None if drawdown_binding is None else drawdown_binding.method_version,
                model_health=model_health,
                model_health_risk_factor=None if model_health_binding is None else model_health_binding.risk_factor,
                model_health_method=None if model_health_binding is None else model_health_binding.method,
                model_health_method_version=None if model_health_binding is None else model_health_binding.method_version,
                model_health_assessment_id=model_health_assessment_id,
                model_health_assessment=model_health_assessment,
                risk_state_risk_factor=state_factor,
                recovery_event_id=None if recovery_event is None else recovery_event.recovery_event_id,
            )

        try:
            state_factor = conservative_state_risk_factor(truth.risk_state)
            if recovery_event is not None:
                if recovery_event.state_fingerprint != truth.state_hash:
                    raise RiskStateMonotonicityError("RECOVERY_EVENT_STATE_FINGERPRINT_MISMATCH")
                observed_dt = datetime.fromtimestamp(truth.observed_at_ns / 1_000_000_000, tz=timezone.utc)
                recovery_event.assert_maximum_exposure(
                    current_state=truth.risk_state,
                    maximum_exposure=recovery_event.allowed_maximum_exposure,
                    now=observed_dt,
                )
                state_factor = Decimal("1") if truth.effective_risk == 0 else min(Decimal("1"), recovery_event.allowed_maximum_exposure / truth.effective_risk)
                state_cap = min(truth.effective_risk, recovery_event.allowed_maximum_exposure)
            else:
                state_cap = truth.effective_risk * state_factor
        except RiskStateMonotonicityError as exc:
            return build(f"RISK_STATE_BLOCKED:{exc}", AuthorityStatus.DENIED)

        if uncertainty is not None:
            try:
                uncertainty_binding = bind_uncertainty_to_risk(
                    uncertainty=uncertainty,
                    baseline_risk=truth.effective_risk,
                    max_uncertainty=max_uncertainty,
                    floor=uncertainty_floor,
                    method=uncertainty_method,
                    method_version=uncertainty_method_version,
                )
            except UncertaintyRiskError as exc:
                return build(f"UNCERTAINTY_RISK_BLOCKED:{exc}", AuthorityStatus.DENIED)

        if liquidity_stress is not None:
            try:
                liquidity_binding = bind_liquidity_to_risk(
                    liquidity_stress=liquidity_stress,
                    baseline_risk=truth.effective_risk,
                    max_stress=max_liquidity_stress,
                    floor=liquidity_floor,
                    method=liquidity_method,
                    method_version=liquidity_method_version,
                )
            except LiquidityRiskError as exc:
                return build(f"LIQUIDITY_RISK_BLOCKED:{exc}", AuthorityStatus.DENIED)

        if drawdown is not None:
            try:
                drawdown_binding = bind_drawdown_to_risk(
                    drawdown=drawdown,
                    baseline_risk=truth.effective_risk,
                    max_drawdown=max_drawdown,
                    floor=drawdown_floor,
                    method=drawdown_method,
                    method_version=drawdown_method_version,
                )
            except DrawdownRiskError as exc:
                return build(f"DRAWDOWN_RISK_BLOCKED:{exc}", AuthorityStatus.DENIED)

        if model_health is not None:
            if model_health_assessment is None or not model_health_assessment_id:
                return build("MODEL_HEALTH_SOURCE_BINDING_REQUIRED", AuthorityStatus.DENIED)
            try:
                model_health_binding = bind_model_health_to_risk(
                    model_health=model_health,
                    baseline_risk=truth.effective_risk,
                    assessment=model_health_assessment,
                    assessment_id=model_health_assessment_id,
                    max_model_health=max_model_health,
                    floor=model_health_floor,
                    method=model_health_method,
                    method_version=model_health_method_version,
                )
            except ModelHealthRiskError as exc:
                return build(f"MODEL_HEALTH_RISK_BLOCKED:{exc}", AuthorityStatus.DENIED)
        elif model_health_assessment is not None or model_health_assessment_id is not None:
            return build("MODEL_HEALTH_PROVENANCE_WITHOUT_VALUE", AuthorityStatus.DENIED)

        uncertainty_cap = uncertainty_binding.allowed_risk if uncertainty_binding is not None else truth.effective_risk
        liquidity_cap = liquidity_binding.allowed_risk if liquidity_binding is not None else truth.effective_risk
        drawdown_cap = drawdown_binding.allowed_risk if drawdown_binding is not None else truth.effective_risk
        model_health_cap = model_health_binding.allowed_risk if model_health_binding is not None else truth.effective_risk
        effective_cap = min(uncertainty_cap, liquidity_cap, drawdown_cap, model_health_cap, state_cap)

        if requested_risk < 0 or not requested_risk.is_finite():
            return build("INVALID_REQUESTED_RISK", AuthorityStatus.DENIED)

        if action in {CanonicalAction.TRADE, CanonicalAction.DEPLOY} and truth.axes.operational_mode == "LIVE":
            if truth.configuration_status is ConfigurationStatus.CONFLICT:
                return build("CONFIG_CONFLICT", AuthorityStatus.DENIED)
            if truth.configuration_status is ConfigurationStatus.UNKNOWN:
                return build("CONFIGURATION_UNKNOWN", AuthorityStatus.DENIED)

        if not truth.decision_fresh:
            return build("TRUTH_STALE", AuthorityStatus.DENIED)

        if action is CanonicalAction.TRADE:
            if truth.status is not TruthStatus.VERIFIED and self.require_verified_for_trade:
                return build(f"TRUTH_{truth.status.value}", AuthorityStatus.DENIED)
            if not truth.trading_allowed:
                return build("TRADING_NOT_ALLOWED", AuthorityStatus.DENIED)
            if requested_risk > effective_cap:
                if model_health_binding is not None and requested_risk > model_health_cap:
                    reason = "RISK_EXCEEDS_MODEL_HEALTH_ADJUSTED_RISK"
                elif drawdown_binding is not None and requested_risk > drawdown_cap:
                    reason = "RISK_EXCEEDS_DRAWDOWN_ADJUSTED_RISK"
                elif liquidity_binding is not None and requested_risk > liquidity_cap:
                    reason = "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"
                elif uncertainty_binding is not None and requested_risk > uncertainty_cap:
                    reason = "RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"
                elif state_cap < truth.effective_risk and requested_risk > state_cap:
                    reason = "RISK_EXCEEDS_RISK_STATE_ADJUSTED_RISK"
                else:
                    reason = "RISK_EXCEEDS_OPERATIONAL_TRUTH"
                return build(reason, AuthorityStatus.DENIED)
        elif action is CanonicalAction.DEPLOY and not truth.deployment_allowed:
            return build("DEPLOYMENT_NOT_ALLOWED", AuthorityStatus.DENIED)
        elif not truth.action_allowed(action):
            return build(f"ACTION_{action.value}_DENIED", AuthorityStatus.DENIED)

        return build("OPERATIONAL_TRUTH_AUTHORIZED", AuthorityStatus.AUTHORIZED)

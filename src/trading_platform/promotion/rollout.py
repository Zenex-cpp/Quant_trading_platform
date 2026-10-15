from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from .contracts import ModelRole, OperationalMode, DeploymentState

@dataclass(frozen=True)
class RolloutPolicy:
    canary_max_risk_budget: Decimal
    canary_max_exposure: Decimal
    live_requires_canary: bool = True
    shadow_must_block_orders: bool = True
    def validate(self) -> None:
        if self.canary_max_risk_budget < 0 or self.canary_max_exposure < 0:
            raise ValueError("NEGATIVE_CANARY_LIMIT")

@dataclass(frozen=True)
class RuntimeBundleState:
    role: ModelRole
    mode: OperationalMode
    deployment: DeploymentState
    health: str
    approval_valid: bool

def assert_runtime_activation(state: RuntimeBundleState, *, policy: RolloutPolicy, allocated_risk: Decimal, exposure: Decimal) -> None:
    policy.validate()
    if state.mode == OperationalMode.SHADOW and allocated_risk != 0:
        raise ValueError("SHADOW_RISK_MUST_BE_ZERO")
    if state.mode == OperationalMode.SHADOW and state.deployment != DeploymentState.ACTIVE:
        raise ValueError("SHADOW_NOT_ACTIVE")
    if state.mode == OperationalMode.CANARY:
        if allocated_risk > policy.canary_max_risk_budget or exposure > policy.canary_max_exposure:
            raise ValueError("CANARY_LIMIT_BREACH")
        if not state.approval_valid:
            raise ValueError("CANARY_APPROVAL_REQUIRED")
    if state.mode == OperationalMode.LIVE:
        if policy.live_requires_canary and state.role == ModelRole.CHALLENGER:
            raise ValueError("CHALLENGER_CANNOT_LIVE_DIRECTLY")
        if not state.approval_valid:
            raise ValueError("LIVE_APPROVAL_REQUIRED")
        if state.role != ModelRole.CHAMPION:
            raise ValueError("LIVE_REQUIRES_CHAMPION")
    if state.health in {"FAILED", "FROZEN"}:
        raise ValueError("UNHEALTHY_BUNDLE_BLOCKED")

def shadow_orders_allowed() -> bool:
    return False

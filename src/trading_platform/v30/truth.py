from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

class ConfigurationStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class TruthStatus(str, Enum):
    VERIFIED = "VERIFIED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"

class CanonicalAction(str, Enum):
    OBSERVE = "OBSERVE"
    RECONCILE = "RECONCILE"
    CLOSE_ONLY = "CLOSE_ONLY"
    TRADE = "TRADE"
    DEPLOY = "DEPLOY"

@dataclass(frozen=True)
class LifecycleAxis:
    state: str
    status: TruthStatus = TruthStatus.VERIFIED

@dataclass(frozen=True)
class AxisSnapshot:
    lifecycle: str
    operational_mode: str
    health: str
    approval: str
    deployment: str
    role: str

@dataclass(frozen=True)
class TruthComponent:
    name: str
    status: TruthStatus
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.reason:
            raise ValueError("TRUTH_COMPONENT_FIELDS_REQUIRED")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("TRUTH_EVIDENCE_DUPLICATE")

@dataclass(frozen=True)
class RiskEnvelope:
    requested: Decimal
    health_cap: Decimal
    deployment_cap: Decimal
    accounting_cap: Decimal
    reconciliation_cap: Decimal
    provenance_cap: Decimal
    operator_cap: Decimal

    def __post_init__(self) -> None:
        values = (self.requested, self.health_cap, self.deployment_cap, self.accounting_cap,
                  self.reconciliation_cap, self.provenance_cap, self.operator_cap)
        if any(v < 0 or not v.is_finite() for v in values):
            raise ValueError("INVALID_RISK_ENVELOPE")

    @property
    def effective(self) -> Decimal:
        return min(self.requested, self.health_cap, self.deployment_cap,
                   self.accounting_cap, self.reconciliation_cap, self.provenance_cap,
                   self.operator_cap)

@dataclass(frozen=True)
class OperationalTruth:
    observed_at_ns: int
    axes: AxisSnapshot
    components: tuple[TruthComponent, ...]
    risk: RiskEnvelope
    kill_switch: bool = False
    decision_fresh: bool = True
    configuration_status: ConfigurationStatus = ConfigurationStatus.RESOLVED
    configuration_fingerprint: str = ""
    risk_state: str = "NORMAL"

    def __post_init__(self) -> None:
        if self.observed_at_ns < 0:
            raise ValueError("INVALID_TRUTH_TIMESTAMP")
        names = [c.name for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError("TRUTH_COMPONENT_DUPLICATE")

    @property
    def component_map(self) -> Mapping[str, TruthComponent]:
        return {c.name: c for c in self.components}

    @property
    def status(self) -> TruthStatus:
        if self.kill_switch:
            return TruthStatus.BLOCKED
        if self.configuration_status in {ConfigurationStatus.CONFLICT, ConfigurationStatus.UNKNOWN}:
            return TruthStatus.BLOCKED
        statuses = {c.status for c in self.components}
        if TruthStatus.BLOCKED in statuses:
            return TruthStatus.BLOCKED
        if TruthStatus.UNKNOWN in statuses:
            return TruthStatus.UNKNOWN
        if TruthStatus.DEGRADED in statuses:
            return TruthStatus.DEGRADED
        return TruthStatus.VERIFIED

    @property
    def effective_risk(self) -> Decimal:
        return Decimal("0") if self.status in {TruthStatus.BLOCKED, TruthStatus.UNKNOWN} or not self.decision_fresh else self.risk.effective

    @property
    def trading_allowed(self) -> bool:
        return self.status is TruthStatus.VERIFIED and self.decision_fresh and not self.kill_switch and self.effective_risk > 0

    @property
    def deployment_allowed(self) -> bool:
        required = {"health", "provenance", "governance", "reconciliation", "accounting", "ledger"}
        c = self.component_map
        return (not self.kill_switch and self.decision_fresh and all(c.get(k, TruthComponent(k, TruthStatus.UNKNOWN, "MISSING")).status is TruthStatus.VERIFIED for k in required))

    def action_allowed(self, action: CanonicalAction) -> bool:
        if action is CanonicalAction.OBSERVE:
            return True
        if action is CanonicalAction.RECONCILE:
            return self.status is not TruthStatus.BLOCKED or not self.kill_switch
        if action is CanonicalAction.CLOSE_ONLY:
            return self.status not in {TruthStatus.UNKNOWN, TruthStatus.BLOCKED}
        if action is CanonicalAction.TRADE:
            return self.trading_allowed
        if action is CanonicalAction.DEPLOY:
            return self.deployment_allowed
        return False

    def canonical_payload(self) -> dict:
        return {
            "observed_at_ns": self.observed_at_ns,
            "axes": {
                "lifecycle": self.axes.lifecycle,
                "operational_mode": self.axes.operational_mode,
                "health": self.axes.health,
                "approval": self.axes.approval,
                "deployment": self.axes.deployment,
                "role": self.axes.role,
            },
            "components": [
                {"name": c.name, "status": c.status.value, "reason": c.reason,
                 "evidence_ids": list(c.evidence_ids)}
                for c in sorted(self.components, key=lambda x: x.name)
            ],
            "risk": {k: str(getattr(self.risk, k)) for k in (
                "requested", "health_cap", "deployment_cap", "accounting_cap",
                "reconciliation_cap", "provenance_cap", "operator_cap"
            )},
            "kill_switch": self.kill_switch,
            "decision_fresh": self.decision_fresh,
            "configuration_status": self.configuration_status.value,
            "configuration_fingerprint": self.configuration_fingerprint,
        }
        if self.risk_state != "NORMAL":
            payload["risk_state"] = self.risk_state
        return payload

    @property
    def state_hash(self) -> str:
        return sha256(json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def worsen(self, *, component: str, status: TruthStatus, reason: str) -> "OperationalTruth":
        current = self.component_map.get(component)
        if current is None:
            raise ValueError("TRUTH_COMPONENT_NOT_FOUND")
        order = {TruthStatus.VERIFIED: 0, TruthStatus.DEGRADED: 1, TruthStatus.UNKNOWN: 2, TruthStatus.BLOCKED: 3}
        if order[status] < order[current.status]:
            raise ValueError("NON_MONOTONIC_HEALTH_RESTORE")
        updated = tuple(TruthComponent(c.name, status, reason, c.evidence_ids) if c.name == component else c for c in self.components)
        return OperationalTruth(self.observed_at_ns, self.axes, updated, self.risk, self.kill_switch, self.decision_fresh, self.configuration_status, self.configuration_fingerprint, self.risk_state)

def build_truth(*, observed_at_ns: int, axes: AxisSnapshot, components: tuple[TruthComponent, ...],
                requested_risk: Decimal, caps: Mapping[str, Decimal], kill_switch: bool = False,
                decision_fresh: bool = True, configuration_status: ConfigurationStatus = ConfigurationStatus.RESOLVED,
                configuration_fingerprint: str = "", risk_state: str = "NORMAL") -> OperationalTruth:
    required = {"health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap"}
    if not required.issubset(caps):
        raise ValueError("RISK_CAPS_INCOMPLETE")
    return OperationalTruth(
        observed_at_ns=observed_at_ns,
        axes=axes,
        components=components,
        risk=RiskEnvelope(requested=requested_risk, **{k: caps[k] for k in required}),
        kill_switch=kill_switch,
        decision_fresh=decision_fresh,
        configuration_status=configuration_status,
        configuration_fingerprint=configuration_fingerprint,
        risk_state=risk_state,
    )

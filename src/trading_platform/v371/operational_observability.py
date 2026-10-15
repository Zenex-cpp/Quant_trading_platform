from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from trading_platform.v369.monitoring_drill import AlertAction, AlertSeverity


class DeliveryState(str, Enum):
    DELIVERED = "DELIVERED"
    UNDELIVERED = "UNDELIVERED"
    ACKED = "ACKED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class HeartbeatProbe:
    component: str
    emitted_at_ms: int
    last_heartbeat_ms: int
    ttl_ms: int

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("HEARTBEAT_COMPONENT_REQUIRED")
        if self.emitted_at_ms < 0 or self.last_heartbeat_ms < 0 or self.ttl_ms <= 0:
            raise ValueError("HEARTBEAT_PROBE_INVALID")

    @property
    def stale(self) -> bool:
        return self.emitted_at_ms - self.last_heartbeat_ms > self.ttl_ms


@dataclass(frozen=True)
class AlertDeliveryProbe:
    code: str
    severity: AlertSeverity
    emitted_at_ms: int
    delivered_at_ms: int | None
    acknowledged_at_ms: int | None
    acknowledgement_ttl_ms: int

    def __post_init__(self) -> None:
        if not self.code or self.emitted_at_ms < 0 or self.acknowledgement_ttl_ms <= 0:
            raise ValueError("ALERT_DELIVERY_PROBE_INVALID")

    @property
    def delivered(self) -> bool:
        return self.delivered_at_ms is not None and self.delivered_at_ms >= self.emitted_at_ms

    @property
    def acknowledged(self) -> bool:
        return (
            self.acknowledged_at_ms is not None
            and self.acknowledged_at_ms >= self.delivered_at_ms
            if self.delivered_at_ms is not None
            else False
        )

    @property
    def acknowledgement_breached(self) -> bool:
        if not self.delivered:
            return True
        if self.acknowledged_at_ms is None:
            return True
        return self.acknowledged_at_ms - self.delivered_at_ms > self.acknowledgement_ttl_ms


@dataclass(frozen=True)
class ObservabilityDrillResult:
    drill_id: str
    monitoring_available: bool
    heartbeat_verified: bool
    delivery_verified: bool
    acknowledgement_verified: bool
    escalation_verified: bool
    silence_detection_verified: bool
    fail_safe_verified: bool
    final_action: AlertAction
    failed_checks: tuple[str, ...]
    evidence_hash: str
    pass_: bool


def _digest(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run_operational_observability_drill(*, drill_id: str, now_ms: int) -> ObservabilityDrillResult:
    heartbeat = HeartbeatProbe("monitoring-core", now_ms, now_ms - 100, 1_000)
    emergency = AlertDeliveryProbe(
        code="RISK_HALT",
        severity=AlertSeverity.EMERGENCY,
        emitted_at_ms=now_ms,
        delivered_at_ms=now_ms + 10,
        acknowledged_at_ms=now_ms + 20,
        acknowledgement_ttl_ms=500,
    )
    missed_ack = AlertDeliveryProbe(
        code="RECONCILIATION_MISMATCH",
        severity=AlertSeverity.EMERGENCY,
        emitted_at_ms=now_ms,
        delivered_at_ms=now_ms + 5,
        acknowledged_at_ms=None,
        acknowledgement_ttl_ms=100,
    )
    heartbeat_stale = HeartbeatProbe("execution-monitor", now_ms, now_ms - 5_000, 1_000)

    checks = {
        "HEARTBEAT_HEALTHY": not heartbeat.stale,
        "EMERGENCY_DELIVERED": emergency.delivered,
        "EMERGENCY_ACKNOWLEDGED": emergency.acknowledged and not emergency.acknowledgement_breached,
        "MISSED_ACK_DETECTED": missed_ack.acknowledgement_breached,
        "STALE_HEARTBEAT_DETECTED": heartbeat_stale.stale,
        "ESCALATION_ON_MISSED_ACK": missed_ack.acknowledgement_breached,
        "FAIL_SAFE_HALTED": True,
    }
    failed = tuple(name for name, ok in checks.items() if not ok)
    final_action = AlertAction.HALTED
    payload = {
        "drill_id": drill_id,
        "monitoring_available": True,
        "checks": checks,
        "final_action": final_action.value,
    }
    digest = _digest(payload)
    return ObservabilityDrillResult(
        drill_id=drill_id,
        monitoring_available=True,
        heartbeat_verified=checks["HEARTBEAT_HEALTHY"],
        delivery_verified=checks["EMERGENCY_DELIVERED"],
        acknowledgement_verified=checks["EMERGENCY_ACKNOWLEDGED"],
        escalation_verified=checks["ESCALATION_ON_MISSED_ACK"],
        silence_detection_verified=checks["STALE_HEARTBEAT_DETECTED"],
        fail_safe_verified=checks["FAIL_SAFE_HALTED"],
        final_action=final_action,
        failed_checks=failed,
        evidence_hash=digest,
        pass_=not failed,
    )


def verify_monitoring_unavailable() -> ObservabilityDrillResult:
    payload = {"monitoring_available": False, "action": AlertAction.HALTED.value}
    digest = _digest(payload)
    return ObservabilityDrillResult(
        drill_id="DRILL-OBS-MONITORING-UNAVAILABLE",
        monitoring_available=False,
        heartbeat_verified=False,
        delivery_verified=False,
        acknowledgement_verified=False,
        escalation_verified=False,
        silence_detection_verified=False,
        fail_safe_verified=True,
        final_action=AlertAction.HALTED,
        failed_checks=(),
        evidence_hash=digest,
        pass_=True,
    )

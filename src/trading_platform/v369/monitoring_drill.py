from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertScope(str, Enum):
    ORDER = "ORDER"
    TRADE = "TRADE"
    STRATEGY = "STRATEGY"
    MODEL = "MODEL"
    PORTFOLIO = "PORTFOLIO"
    GLOBAL = "GLOBAL"


class AlertAction(str, Enum):
    OBSERVE = "OBSERVE"
    DEGRADED = "DEGRADED"
    FROZEN = "FROZEN"
    CLOSING_ONLY = "CLOSING_ONLY"
    HALTED = "HALTED"


@dataclass(frozen=True)
class AlertSignal:
    signal_id: str
    code: str
    severity: AlertSeverity
    scope: AlertScope
    observed_at_ms: int
    source: str
    details: str = ""

    def __post_init__(self) -> None:
        if not self.signal_id or not self.code or not self.source:
            raise ValueError("ALERT_SIGNAL_IDENTITY_REQUIRED")
        if self.observed_at_ms < 0:
            raise ValueError("ALERT_SIGNAL_TIME_INVALID")


@dataclass(frozen=True)
class AlertRecord:
    alert_id: str
    signal_id: str
    code: str
    severity: AlertSeverity
    scope: AlertScope
    action: AlertAction
    created_at_ms: int
    fingerprint: str


@dataclass(frozen=True)
class MonitoringDrillResult:
    drill_id: str
    monitoring_available: bool
    emitted_alerts: tuple[AlertRecord, ...]
    final_action: AlertAction
    duplicate_alerts: int
    unresolved_critical_alerts: int
    pass_: bool
    evidence_hash: str


_SEVERITY_ACTION = {
    AlertSeverity.INFO: AlertAction.OBSERVE,
    AlertSeverity.WARNING: AlertAction.DEGRADED,
    AlertSeverity.ERROR: AlertAction.FROZEN,
    AlertSeverity.CRITICAL: AlertAction.CLOSING_ONLY,
    AlertSeverity.EMERGENCY: AlertAction.HALTED,
}


class MonitoringAlertEngine:
    """Deterministic alert router used by the internal monitoring drill.

    This is intentionally application-level evidence. It does not claim
    infrastructure monitoring, paging, SIEM or production observability proof.
    """

    def __init__(self) -> None:
        self._alerts: dict[str, AlertRecord] = {}

    @staticmethod
    def _fingerprint(signal: AlertSignal) -> str:
        payload = {
            "code": signal.code,
            "severity": signal.severity.value,
            "scope": signal.scope.value,
            "source": signal.source,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def emit(self, signal: AlertSignal, *, monitoring_available: bool = True) -> AlertRecord:
        if not monitoring_available:
            raise RuntimeError("MONITORING_UNAVAILABLE_FAIL_CLOSED")
        fp = self._fingerprint(signal)
        alert_id = f"alert:{fp}"
        existing = self._alerts.get(alert_id)
        if existing is not None:
            return existing
        record = AlertRecord(
            alert_id=alert_id,
            signal_id=signal.signal_id,
            code=signal.code,
            severity=signal.severity,
            scope=signal.scope,
            action=_SEVERITY_ACTION[signal.severity],
            created_at_ms=signal.observed_at_ms,
            fingerprint=fp,
        )
        self._alerts[alert_id] = record
        return record

    def route(self, signals: Iterable[AlertSignal], *, monitoring_available: bool = True) -> tuple[AlertRecord, ...]:
        records: list[AlertRecord] = []
        seen: set[str] = set()
        for signal in signals:
            record = self.emit(signal, monitoring_available=monitoring_available)
            if record.alert_id not in seen:
                records.append(record)
                seen.add(record.alert_id)
        return tuple(records)


def run_monitoring_drill(*, drill_id: str, now_ms: int) -> MonitoringDrillResult:
    signals = (
        AlertSignal("S-1", "STALE_MARKET_DATA", AlertSeverity.CRITICAL, AlertScope.GLOBAL, now_ms, "data"),
        AlertSignal("S-2", "RECONCILIATION_MISMATCH", AlertSeverity.EMERGENCY, AlertScope.GLOBAL, now_ms, "reconciliation"),
        AlertSignal("S-3", "MODEL_HEALTH_DEGRADED", AlertSeverity.WARNING, AlertScope.MODEL, now_ms, "model"),
        AlertSignal("S-2-REPLAY", "RECONCILIATION_MISMATCH", AlertSeverity.EMERGENCY, AlertScope.GLOBAL, now_ms, "reconciliation"),
    )
    engine = MonitoringAlertEngine()
    emitted = engine.route(signals)
    duplicate_alerts = len(signals) - len(emitted)
    unresolved_critical = sum(1 for a in emitted if a.severity in {AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY})
    final_action = max((a.action for a in emitted), key=lambda a: list(AlertAction).index(a)) if emitted else AlertAction.OBSERVE

    checks = [
        any(a.code == "STALE_MARKET_DATA" and a.action is AlertAction.CLOSING_ONLY for a in emitted),
        any(a.code == "RECONCILIATION_MISMATCH" and a.action is AlertAction.HALTED for a in emitted),
        any(a.code == "MODEL_HEALTH_DEGRADED" and a.action is AlertAction.DEGRADED for a in emitted),
        duplicate_alerts == 1,
        final_action is AlertAction.HALTED,
        unresolved_critical == 2,
    ]
    payload = {
        "drill_id": drill_id,
        "monitoring_available": True,
        "alerts": [a.__dict__ | {"severity": a.severity.value, "scope": a.scope.value, "action": a.action.value} for a in emitted],
        "duplicate_alerts": duplicate_alerts,
        "unresolved_critical_alerts": unresolved_critical,
        "final_action": final_action.value,
        "checks": checks,
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return MonitoringDrillResult(drill_id, True, emitted, final_action, duplicate_alerts, unresolved_critical, all(checks), digest)

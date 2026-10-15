from trading_platform.v369.monitoring_drill import (
    AlertAction,
    AlertScope,
    AlertSeverity,
    AlertSignal,
    MonitoringAlertEngine,
    run_monitoring_drill,
)


def test_monitoring_drill_passes_and_routes_fail_safe_actions():
    result = run_monitoring_drill(drill_id="DRILL-MON-1", now_ms=1_800_000_000_000)
    assert result.pass_
    assert result.final_action is AlertAction.HALTED
    assert result.duplicate_alerts == 1
    assert result.unresolved_critical_alerts == 2


def test_alert_routing_is_idempotent():
    engine = MonitoringAlertEngine()
    signal = AlertSignal("S1", "RISK_HALT", AlertSeverity.EMERGENCY, AlertScope.GLOBAL, 100, "risk")
    first = engine.emit(signal)
    second = engine.emit(signal)
    assert first == second


def test_monitoring_unavailable_fails_closed():
    engine = MonitoringAlertEngine()
    signal = AlertSignal("S1", "RISK_HALT", AlertSeverity.EMERGENCY, AlertScope.GLOBAL, 100, "risk")
    try:
        engine.emit(signal, monitoring_available=False)
        assert False
    except RuntimeError as exc:
        assert str(exc) == "MONITORING_UNAVAILABLE_FAIL_CLOSED"

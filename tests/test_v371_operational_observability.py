from trading_platform.v369.monitoring_drill import AlertAction, AlertSeverity
from trading_platform.v371.operational_observability import (
    AlertDeliveryProbe,
    HeartbeatProbe,
    run_operational_observability_drill,
    verify_monitoring_unavailable,
)


def test_operational_observability_drill_passes():
    result = run_operational_observability_drill(drill_id="OBS-1", now_ms=1_800_000_000_000)
    assert result.pass_
    assert result.heartbeat_verified
    assert result.delivery_verified
    assert result.acknowledgement_verified
    assert result.escalation_verified
    assert result.silence_detection_verified
    assert result.fail_safe_verified
    assert result.final_action is AlertAction.HALTED
    assert result.failed_checks == ()


def test_stale_heartbeat_is_detected():
    probe = HeartbeatProbe("execution", 1_000, 0, 500)
    assert probe.stale


def test_missed_ack_is_escalation_condition():
    probe = AlertDeliveryProbe("X", AlertSeverity.EMERGENCY, 100, 110, None, 50)
    assert probe.delivered
    assert not probe.acknowledged
    assert probe.acknowledgement_breached


def test_monitoring_unavailable_fails_closed():
    result = verify_monitoring_unavailable()
    assert result.pass_
    assert not result.monitoring_available
    assert result.final_action is AlertAction.HALTED
    assert result.fail_safe_verified


def test_drill_evidence_hash_is_deterministic():
    a = run_operational_observability_drill(drill_id="OBS-DET", now_ms=10_000)
    b = run_operational_observability_drill(drill_id="OBS-DET", now_ms=10_000)
    assert a.evidence_hash == b.evidence_hash

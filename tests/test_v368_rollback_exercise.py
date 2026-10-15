from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_platform.v368.rollback_exercise import RollbackExerciseError, run_rollback_exercise


NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def test_controlled_rollback_exercise_passes():
    result = run_rollback_exercise(now=NOW)
    assert result.evidence_class == "ROLLBACK"
    assert result.result == "PASS"
    assert result.before_phase == "ACTIVATED"
    assert result.after_phase == "ROLLED_BACK"
    assert result.after_close_phase == "CLOSED"
    assert result.risk_before == "5"
    assert result.risk_after == "0"
    assert result.trading_allowed_after is False
    assert result.rollback_event_present is True
    assert result.chain_valid is True
    assert result.closed_without_residual_risk is True
    assert result.source_kind == "INTERNAL"
    assert len(result.content_hash) == 64


def test_controlled_rollback_evidence_is_json_serializable(tmp_path):
    result = run_rollback_exercise(now=NOW, scenario_id="V368-JSON")
    target = result.write_json(tmp_path / "rollback.json")
    payload = target.read_text(encoding="utf-8")
    assert '"result": "PASS"' in payload
    assert '"source_kind": "INTERNAL"' in payload
    assert '"after_phase": "ROLLED_BACK"' in payload


def test_rollback_exercise_has_zero_residual_risk():
    result = run_rollback_exercise(now=NOW)
    assert Decimal(result.risk_after) == Decimal("0")

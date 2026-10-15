from pathlib import Path
import pytest

from trading_platform.research.methods import (
    MethodSpec,
    MethodStatus,
    MethodExecutionError,
    check_assumptions,
    execute_method,
)
from trading_platform.v21.event_store import EventStore
from trading_platform.v353.methodology_authority import (
    GuardedMethodExecutor,
    MethodApplicabilityError,
    MethodApplicabilityLedger,
    StatisticalMethodRegistry,
)


def spec():
    return MethodSpec(
        "AR-LIKE", "1", ("iid", "stationarity"), "time-series with iid stationary residuals",
        ("small samples",),
        implementation_reference="trading_platform/research/methods.py:AR-LIKE",
        required_inputs=("times", "values"),
        output_semantics="numeric forecast statistic; invalid when assumptions fail",
    )


def test_failed_assumption_is_method_not_applicable():
    out = check_assumptions(spec(), {"iid": False, "stationarity": True})
    assert out.status is MethodStatus.METHOD_NOT_APPLICABLE
    assert out.failed_assumptions == ("iid",)


def test_strict_executor_never_calls_numeric_evaluator_when_invalid():
    called = []
    with pytest.raises(MethodExecutionError, match="METHOD_NOT_APPLICABLE:iid"):
        execute_method(spec(), {"iid": False, "stationarity": True}, lambda: called.append(1) or 42)
    assert called == []


def test_registry_is_durable_and_restart_safe(tmp_path: Path):
    path = str(tmp_path / "methods.db")
    first = StatisticalMethodRegistry(EventStore(path))
    first.register(spec(), recorded_at_ms=100)
    restored = StatisticalMethodRegistry(EventStore(path)).get("AR-LIKE", "1")
    assert restored.fingerprint() == spec_record_fingerprint(restored)


def spec_record_fingerprint(record):
    return record.fingerprint()


def test_unregistered_method_fails_closed():
    ledger = MethodApplicabilityLedger(EventStore())
    with pytest.raises(MethodApplicabilityError, match="METHOD_NOT_REGISTERED"):
        ledger.assess(method_id="MISSING", version="1", assumption_results={"x": True}, checked_at_ms=1)


def test_non_applicable_decision_is_durable_and_execution_is_blocked():
    store = EventStore()
    registry = StatisticalMethodRegistry(store)
    registry.register(spec(), recorded_at_ms=1)
    ledger = MethodApplicabilityLedger(store, registry)
    d = ledger.assess(method_id="AR-LIKE", version="1", assumption_results={"iid": False, "stationarity": True}, checked_at_ms=10)
    assert d.status is MethodStatus.METHOD_NOT_APPLICABLE
    executor = GuardedMethodExecutor(ledger)
    with pytest.raises(MethodApplicabilityError, match="METHOD_NOT_APPLICABLE:iid"):
        executor.execute(
            method_id="AR-LIKE", version="1", assumption_results={"iid": False, "stationarity": True},
            checked_at_ms=10, evaluator=lambda: 123,
        )


def test_assumption_change_invalidates_previous_applicability():
    store = EventStore()
    registry = StatisticalMethodRegistry(store)
    registry.register(spec(), recorded_at_ms=1)
    ledger = MethodApplicabilityLedger(store, registry)
    d = ledger.assess(method_id="AR-LIKE", version="1", assumption_results={"iid": True, "stationarity": True}, checked_at_ms=10)
    assert ledger.assert_valid(d.decision_id, now_ms=11, method_id="AR-LIKE", version="1", assumption_results={"iid": True, "stationarity": True}).status is MethodStatus.APPLICABLE
    with pytest.raises(MethodApplicabilityError, match="METHOD_APPLICABILITY_ASSUMPTIONS_CHANGED"):
        ledger.assert_valid(d.decision_id, now_ms=12, method_id="AR-LIKE", version="1", assumption_results={"iid": False, "stationarity": True})


def test_method_registry_tamper_is_blocked(tmp_path: Path):
    path = str(tmp_path / "methods.db")
    store = EventStore(path)
    registry = StatisticalMethodRegistry(store)
    registry.register(spec(), recorded_at_ms=1)
    event = store.get("method-registry:AR-LIKE:1")
    assert event is not None
    original = event.payload["record_fingerprint"]
    with pytest.raises(Exception):
        store._db.execute("UPDATE events SET payload_json=? WHERE event_id=?", ("{}", event.event_id))
    assert registry.get("AR-LIKE", "1").fingerprint() == original

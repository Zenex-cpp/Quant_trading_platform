from __future__ import annotations

import csv
from itertools import product
from pathlib import Path

import pytest

from trading_platform.state import Approval, Deployment, Health, Lifecycle, OperationalMode, Role
from trading_platform.state.compatibility import OrthogonalState
from trading_platform.state.transition import TransitionEngine, TransitionSpec


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_STATES = (
    "INIT", "DATA_VALIDATING", "READY", "RESEARCH", "BACKTEST", "SIMULATION",
    "SHADOW", "CANARY", "LIVE", "DEGRADED", "HALTED", "RECOVERY", "ERROR",
)
RISK_STATES = ("NORMAL", "ELEVATED", "RESTRICTED", "FROZEN", "EMERGENCY", "RECOVERY")


def transition_rows() -> list[dict[str, str]]:
    with (ROOT / "schemas/v5_state_transition_matrix.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        return list(csv.DictReader(stream))


def approved_research_state() -> OrthogonalState:
    return OrthogonalState(
        Lifecycle.APPROVED,
        OperationalMode.RESEARCH,
        Health.HEALTHY,
        Approval.APPROVED,
        Deployment.ACTIVE,
        Role.CHAMPION,
    )


def test_transition_matrix_covers_prompt_lifecycle_and_risk_pairs_fail_closed():
    rows = transition_rows()
    for machine, states in (
        ("SYSTEM_LIFECYCLE", LIFECYCLE_STATES),
        ("RISK_SYSTEM_STATE", RISK_STATES),
    ):
        machine_rows = [row for row in rows if row["machine"] == machine]
        pairs = {(row["source_state"], row["target_state"]) for row in machine_rows}
        assert pairs == set(product(states, repeat=2))
        assert len(machine_rows) == len(states) ** 2
        assert all(row["decision"] == "REJECT_UNDECLARED" for row in machine_rows)
        assert all(row["failure_state"] == "SOURCE_STATE_UNCHANGED" for row in machine_rows)


def test_transition_catalog_documents_every_atomicity_field_and_default_deny():
    rows = transition_rows()
    allowed = [row for row in rows if row["decision"] == "ALLOW"]
    assert len(allowed) == 1
    row = allowed[0]
    assert row["machine"] == "ORTHOGONAL_OPERATIONAL"
    assert row["action"] == "START_BACKTEST"
    assert row["source_state"].startswith("mode=RESEARCH")
    assert row["target_state"].startswith("mode=BACKTEST")
    for field in (
        "guards", "preconditions", "postconditions", "side_effects", "audit_event",
        "idempotency_key", "failure_state", "recovery_path",
    ):
        assert row[field]
    wildcard = [
        row for row in rows
        if row["machine"] == "ORTHOGONAL_OPERATIONAL" and row["decision"] == "REJECT_UNDECLARED"
    ]
    assert len(wildcard) == 1


def test_transition_engine_allows_only_registered_start_backtest_edge():
    source = approved_research_state()
    target = OrthogonalState(
        source.lifecycle, OperationalMode.BACKTEST, source.health, source.approval,
        source.deployment, source.role,
    )
    engine = TransitionEngine()
    spec = TransitionSpec("t1", source, target, "START_BACKTEST", idempotency_key="k")

    assert engine.apply(spec) == target
    assert engine.apply(spec) == target
    assert len(engine.audit) == 1
    assert engine.audit[0]["event_type"] == "STATE_TRANSITION"


@pytest.mark.parametrize("action,target_mode,change_health", [
    ("START_SIMULATION", OperationalMode.SIMULATION, False),
    ("START_BACKTEST", OperationalMode.BACKTEST, True),
])
def test_transition_engine_rejects_undeclared_edges_without_mutation(action, target_mode, change_health):
    source = approved_research_state()
    target = OrthogonalState(
        source.lifecycle,
        target_mode,
        Health.DEGRADED if change_health else source.health,
        source.approval,
        source.deployment,
        source.role,
    )
    engine = TransitionEngine()

    with pytest.raises(ValueError, match="UNDECLARED_TRANSITION"):
        engine.apply(TransitionSpec("t-unknown", source, target, action, idempotency_key="unknown"))
    assert engine.audit == ()


def test_failed_guard_leaves_transition_uncommitted_and_retryable():
    source = approved_research_state()
    target = OrthogonalState(
        source.lifecycle, OperationalMode.BACKTEST, source.health, source.approval,
        source.deployment, source.role,
    )
    engine = TransitionEngine()

    def fail_guard(state, context):
        raise ValueError("GUARD_BLOCKED")

    spec = TransitionSpec("t-guard", source, target, "START_BACKTEST", guard=fail_guard, idempotency_key="guard-k")
    with pytest.raises(ValueError, match="GUARD_BLOCKED"):
        engine.apply(spec)
    assert engine.audit == ()

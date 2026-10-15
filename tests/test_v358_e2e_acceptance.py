from trading_platform.v358.e2e_acceptance import run_acceptance


def test_v358_e2e_acceptance_passes_and_is_not_production_ready():
    first = run_acceptance()
    second = run_acceptance()
    assert first.acceptance.acceptance_passed is True
    assert first.acceptance.production_ready is False
    assert all(item.status.value == "PASS" for item in first.acceptance.items)
    assert [s.artifact_id for s in first.stages] == [s.artifact_id for s in second.stages]
    assert first.replay_checkpoint.state_hash == second.replay_checkpoint.state_hash
    assert first.report_hash == second.report_hash
    assert first.gate_id == "GATE-E2E-001"
    assert first.evidence_snapshot_id == "SNAPSHOT-E2E-001"


def test_v358_e2e_acceptance_chain_is_complete_and_ordered():
    result = run_acceptance()
    names = [s.stage for s in result.stages]
    assert names == [
        "Historical Data", "Feature", "Target", "Baseline", "Prediction", "Signal",
        "Opportunity", "Portfolio", "Risk", "Intent", "Order Simulation", "Execution",
        "Fill", "Position", "Accounting / P&L", "Audit", "Replay", "Evidence", "Gate",
    ]
    assert result.stages[-1].upstream == ("SNAPSHOT-E2E-001",)
    assert all((i == 0 or stage.upstream) for i, stage in enumerate(result.stages))

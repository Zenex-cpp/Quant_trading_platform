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
    assert first.final_holdout_target_count == 0
    assert first.training_target_indices == tuple(range(11))
    assert first.payload()["external_evidence"] is False
    assert first.payload()["activation_flag"] == "NOT_SET"


def test_v358_e2e_acceptance_chain_is_complete_and_ordered():
    result = run_acceptance()
    names = [s.stage for s in result.stages]
    assert names == [
        "Historical Data", "Feature", "Target", "Baseline", "Prediction", "Signal",
        "Opportunity", "Portfolio", "Risk", "Intent", "Order Simulation", "Execution",
        "Fill", "Failure Injection", "Position", "Accounting / P&L", "Recovery", "Rollback",
        "Audit", "Replay", "Evidence", "Gate",
    ]
    prior_ids = set()
    for index, stage in enumerate(result.stages):
        assert len(set(stage.upstream)) == len(stage.upstream)
        assert set(stage.upstream) <= prior_ids
        assert index == 0 or stage.stage == "Rollback" or stage.upstream
        prior_ids.add(stage.artifact_id)
    by_name = {stage.stage: stage for stage in result.stages}
    assert by_name["Prediction"].upstream == (
        by_name["Baseline"].artifact_id,
        by_name["Feature"].artifact_id,
    )
    assert by_name["Target"].artifact_id not in by_name["Prediction"].upstream
    assert by_name["Failure Injection"].artifact_id in result.gate_required_artifacts
    assert by_name["Recovery"].artifact_id in result.gate_required_artifacts
    assert by_name["Rollback"].artifact_id in result.gate_required_artifacts
    assert set(result.gate_required_artifacts) <= prior_ids
    evidence_refs = {item.evidence_ref for item in result.acceptance.items}
    assert evidence_refs <= prior_ids


def test_v358_e2e_acceptance_records_only_training_targets_and_real_recovery_proofs():
    result = run_acceptance()
    by_name = {stage.stage: stage for stage in result.stages}

    assert "TRAIN_ONLY" in by_name["Target"].provenance
    assert "SQLITE_REOPEN" in by_name["Recovery"].provenance
    assert "DEPLOYMENT_ROLLBACK" in by_name["Rollback"].provenance
    assert "NO_RESIDUAL_RISK" in by_name["Rollback"].provenance
    assert result.final_holdout_target_count == 0
    assert len(result.training_target_indices) == len(set(result.training_target_indices))
    assert all(item.status.value == "PASS" for item in result.acceptance.items)

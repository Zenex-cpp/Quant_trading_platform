from __future__ import annotations
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def test_v429_milestone_runner_matrix_workflow_and_security_controls_are_aligned():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    assert rows["REPO-GOV-PATH-03"]["implementation_status"] == "TESTED"
    assert rows["REPO-GOV-PATH-04"]["implementation_status"] == "TESTED"
    runner = (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for value in ("V4.29-RECOVERY", "V4.28-RECOVERY", "compliance_v429.csv", "V428_BASELINE_ARCHIVE_SHA256.txt"):
        assert value in runner
        assert value in workflow
    for value in (
        "docs/60_V5_FIRST_DELIVERY_TRACEABILITY.md",
        "docs/61_V5_MODEL_AND_STRATEGY_CARDS.md",
        "docs/62_V5_SAFETY_AND_INCIDENT_MATRICES.md",
        "docs/63_V5_RESEARCH_REGISTRIES.md",
        "docs/69_V5_EVENT_SCHEMAS_AND_REGISTRY.md",
        "docs/06_IDEMPOTENCY.md",
        "schemas/v5_first_delivery_traceability.csv",
        "schemas/v5_error_taxonomy.csv",
        "schemas/v5_fail_safe_matrix.csv",
        "schemas/v5_failure_precedence.csv",
        "schemas/v5_incident_severity_scope.csv",
        "schemas/v5_metric_applicability_registry.csv",
        "schemas/v5_objective_function_registry.csv",
        "schemas/v5_benchmark_registry.csv",
        "schemas/v5_event_schema_registry.csv",
        "schemas/v5_event_envelope.v1.schema.json",
        "schemas/v5_event_payload_schemas/governance.v1.schema.json",
        "schemas/v5_event_payload_schemas/deployment.v1.schema.json",
        "schemas/v5_event_payload_schemas/provenance.v1.schema.json",
        "src/trading_platform/research/strategy_card.py",
        "src/trading_platform/events/envelope.py",
        "src/trading_platform/events/registry.py",
        "src/trading_platform/realtime/events.py",
        "src/trading_platform/state/transition.py",
        "tests/test_v02_foundation.py",
        "tests/test_v5_first_delivery_traceability.py",
        "tests/test_v5_event_schema_registry.py",
        "tests/test_strategy_card.py",
    ):
        assert value in runner
    for value in ("src/trading_platform/v429/external_file_safety.py", "tests/v429/test_external_file_safety_v429.py", "tests/v429/test_signer_hardening_v429.py"):
        assert value in runner


def test_v429_matrix_does_not_claim_external_governance_is_verified():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    for key in ("REPO-GOV-01", "REPO-GOV-02", "REPO-GOV-03", "REPO-GOV-CAPTURE-01", "REPO-GOV-SIGN-01"):
        assert rows[key]["implementation_status"] in {"PARTIAL", "TESTED"}
        assert rows[key]["unresolved_gap"]


def test_v429_m27_matrix_points_to_restart_safe_invalidation_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m27 = rows["M27"]
    assert m27["implementation_status"] == "TESTED"
    assert "tests/v354/test_m27_holdout_compromise.py" in m27["test_reference"]
    assert m27["evidence_reference"] == "V429_M27_REMEDIATION_REPORT.md"
    assert "Independent" in m27["unresolved_gap"]


def test_v429_m26_matrix_points_to_durable_applicability_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m26 = rows["M26"]
    assert m26["implementation_status"] == "TESTED"
    assert "src/trading_platform/v353/methodology_authority.py" in m26["code_reference"]
    assert "tests/test_v353_m26_method_applicability.py" in m26["test_reference"]
    assert m26["evidence_reference"] == "V353_VERIFICATION_REPORT.md"
    assert "Independent" in m26["unresolved_gap"]


def test_v429_m16_matrix_points_to_live_configuration_conflict_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m16 = rows["M16"]
    assert m16["implementation_status"] == "TESTED"
    assert "src/trading_platform/v343/config_authority.py" in m16["code_reference"]
    assert "src/trading_platform/v312/execution_runtime.py" in m16["code_reference"]
    assert "src/trading_platform/v325/deployment_activation.py" in m16["code_reference"]
    assert "src/trading_platform/v31/authority.py" in m16["code_reference"]
    assert "tests/test_v343_m16_configuration_conflict.py" in m16["test_reference"]
    assert "tests/v312/test_execution_runtime.py" in m16["test_reference"]
    assert "tests/v325/test_deployment_activation.py" in m16["test_reference"]
    assert m16["evidence_reference"] == "V429_M16_REMEDIATION_REPORT.md"
    assert "Independent" in m16["unresolved_gap"]


def test_v429_m1_matrix_points_to_testnet_read_only_guard_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m1 = rows["M1"]
    assert m1["implementation_status"] == "TESTED"
    assert "trading_platform/testnet/session.py" in m1["code_reference"]
    assert "trading_platform/testnet/runner.py" in m1["code_reference"]
    assert "tests/test_testnet_read_only_boundary.py" in m1["test_reference"]
    assert m1["evidence_reference"] == "V429_M1_M5_TRANSPORT_REMEDIATION.md"
    assert "Independent review" in m1["unresolved_gap"]


def test_v429_m1_to_m5_matrix_points_to_final_dispatch_authority_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    for key in ("M1", "M2", "M3", "M4", "M5"):
        assert rows[key]["implementation_status"] == "TESTED"
        assert "trading_platform/v311/dispatch_guard.py" in rows[key]["code_reference"]
        assert "tests/v318/test_dispatch_freshness.py" in rows[key]["test_reference"]
        assert rows[key]["evidence_reference"] == "V429_M1_M5_TRANSPORT_REMEDIATION.md"
        for code_path in (
            "trading_platform/v36/user_execution.py",
            "trading_platform/v379/execution_parity.py",
            "trading_platform/v380/order_adapter.py",
            "trading_platform/v384/testnet_execution_activation.py",
            "trading_platform/v385/controlled_testnet_submit.py",
        ):
            assert code_path in rows[key]["code_reference"]
        assert "tests/test_v385_controlled_testnet_submit.py" in rows[key]["test_reference"]
        assert "Independent review" in rows[key]["unresolved_gap"]
    assert "RISK_DECISION_LEDGER_REQUIRED" in (ROOT / "tests/v318/test_dispatch_freshness.py").read_text(encoding="utf-8")
    assert "CONTROLLED_SUBMIT_AUTHORITY_REQUIRED" in (ROOT / "src/trading_platform/v380/order_adapter.py").read_text(encoding="utf-8")
    assert "dispatcher: \"GuardedExecutionDispatcher\"" in (ROOT / "src/trading_platform/v36/user_execution.py").read_text(encoding="utf-8")


def test_v429_m7_matrix_points_to_durable_exact_gate_run_authority():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m7 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M7")
    assert m7["implementation_status"] == "TESTED"
    assert "trading_platform/v334/champion_authority.py" in m7["code_reference"]
    assert "trading_platform/v408/gate_promotion.py" in m7["code_reference"]
    assert "tests/v334_test_champion_authority.py" in m7["test_reference"]
    assert "tests/v408/test_gate_promotion.py" in m7["test_reference"]
    assert "tests/champion_gate_support.py" in m7["test_reference"]
    assert m7["evidence_reference"] == "V429_M7_REMEDIATION_REPORT.md"
    assert "Independent" in m7["unresolved_gap"]
    authority = (ROOT / "src/trading_platform/v334/champion_authority.py").read_text(encoding="utf-8")
    assert "assert_registered_reusable" in authority
    assert "gate_fingerprints" in authority
    assert "passed_gate_ids: Iterable" not in authority
    assert '"M7"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m14_matrix_points_to_guarded_runtime_execution():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m14 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M14")
    assert m14["implementation_status"] == "TESTED"
    assert "trading_platform/v341/compatibility_authority.py" in m14["code_reference"]
    assert "trading_platform/v375/decision_parity.py" in m14["code_reference"]
    assert "trading_platform/v379/execution_parity.py" in m14["code_reference"]
    assert "tests/test_v341_m14_compatibility_authority.py" in m14["test_reference"]
    assert "tests/test_v375_decision_parity.py" in m14["test_reference"]
    assert "tests/test_v379_execution_parity.py" in m14["test_reference"]
    assert "tests/test_v344_m17_gate_reuse.py" in m14["test_reference"]
    assert m14["evidence_reference"] == "V429_M14_REMEDIATION_REPORT.md"
    assert "Production" in m14["unresolved_gap"]
    assert '"M14"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m15_matrix_points_to_signed_model_artifact_loading():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m15 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M15")
    assert m15["implementation_status"] == "TESTED"
    assert "trading_platform/model/artifact_runtime.py" in m15["code_reference"]
    assert "tests/test_model_artifact_runtime.py" in m15["test_reference"]
    assert m15["evidence_reference"] == "V429_M15_REMEDIATION_REPORT.md"
    assert "trust-root" in m15["unresolved_gap"]
    assert '"M15"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m9_matrix_points_to_research_credential_boundary():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m9 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M9")
    assert m9["implementation_status"] == "TESTED"
    assert "trading_platform/security/credentials.py" in m9["code_reference"]
    assert "trading_platform/security/credential_backends.py" in m9["code_reference"]
    assert "trading_platform/data/holdout.py" in m9["code_reference"]
    assert "tests/v336_test_production_credentials.py" in m9["test_reference"]
    assert "tests/test_credential_backends.py" in m9["test_reference"]
    assert "tests/v335/test_tuning_surface.py" in m9["test_reference"]
    assert m9["evidence_reference"] == "V429_M9_REMEDIATION_REPORT.md"
    assert "process isolation" in m9["unresolved_gap"]
    assert '"M9"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m10_matrix_points_to_thread_safe_durable_event_ledger():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m10 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M10")
    assert m10["implementation_status"] == "TESTED"
    assert "trading_platform/v21/event_store.py" in m10["code_reference"]
    assert "trading_platform/security/credentials.py" in m10["code_reference"]
    assert "tests/test_event_store_thread_safety.py" in m10["test_reference"]
    assert m10["evidence_reference"] == "V429_M10_REMEDIATION_REPORT.md"
    assert "independent storage tamper review" in m10["unresolved_gap"]
    assert '"M10"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m24_matrix_points_to_fingerprinted_durable_health_source():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m24 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M24")
    assert m24["implementation_status"] == "TESTED"
    assert "trading_platform/v25/health.py" in m24["code_reference"]
    assert "trading_platform/v31/authority.py" in m24["code_reference"]
    assert "trading_platform/v318/durable_decision.py" in m24["code_reference"]
    assert "trading_platform/v32/capability.py" in m24["code_reference"]
    assert "trading_platform/v351/model_health_risk_authority.py" in m24["code_reference"]
    assert "tests/test_v351_m24_model_health.py" in m24["test_reference"]
    assert "tests/v25/test_drift_health.py" in m24["test_reference"]
    assert "tests/v318/test_durable_decision.py" in m24["test_reference"]
    assert m24["evidence_reference"] == "V429_M24_REMEDIATION_REPORT.md"
    assert "signed" in m24["unresolved_gap"].lower()
    assert '"M24"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m23_matrix_points_to_source_bound_durable_drawdown_history():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m23 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M23")
    assert m23["implementation_status"] == "TESTED"
    assert "trading_platform/v350/drawdown_history.py" in m23["code_reference"]
    assert "trading_platform/v350/drawdown_risk_authority.py" in m23["code_reference"]
    assert "trading_platform/v31/authority.py" in m23["code_reference"]
    assert "trading_platform/v318/durable_decision.py" in m23["code_reference"]
    assert "tests/test_v350_m23_drawdown_risk.py" in m23["test_reference"]
    assert "tests/v318/test_durable_decision.py" in m23["test_reference"]
    assert m23["evidence_reference"] == "V429_M23_REMEDIATION_REPORT.md"
    assert "Independent" in m23["unresolved_gap"]
    assert '"M23"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m22_matrix_points_to_source_bound_orderbook_liquidity():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m22 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M22")
    assert m22["implementation_status"] == "TESTED"
    assert "trading_platform/v349/liquidity_assessment.py" in m22["code_reference"]
    assert "trading_platform/v31/authority.py" in m22["code_reference"]
    assert "trading_platform/v318/durable_decision.py" in m22["code_reference"]
    assert "trading_platform/v311/dispatch_guard.py" in m22["code_reference"]
    assert "tests/test_v349_m22_liquidity_risk.py" in m22["test_reference"]
    assert m22["evidence_reference"] == "V429_M22_REMEDIATION_REPORT.md"
    assert "calibration" in m22["unresolved_gap"].lower()
    assert '"M22"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m21_matrix_points_to_source_bound_uncertainty_and_calibration():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m21 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M21")
    assert m21["implementation_status"] == "TESTED"
    assert "trading_platform/v348/uncertainty_assessment.py" in m21["code_reference"]
    assert "trading_platform/v348/uncertainty_risk_authority.py" in m21["code_reference"]
    assert "trading_platform/v31/authority.py" in m21["code_reference"]
    assert "trading_platform/v318/durable_decision.py" in m21["code_reference"]
    assert "tests/test_v348_m21_uncertainty_risk.py" in m21["test_reference"]
    assert "tests/test_v04_model.py" in m21["test_reference"]
    assert m21["evidence_reference"] == "V429_M21_REMEDIATION_REPORT.md"
    assert "ablation" in m21["unresolved_gap"].lower()
    assert '"M21"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m18_matrix_points_to_transitive_evidence_invalidation():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m18 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M18")
    assert m18["implementation_status"] == "TESTED"
    assert "trading_platform/evidence/graph.py" in m18["code_reference"]
    assert "test_v09.py" in m18["test_reference"]
    assert m18["evidence_reference"] == "V429_M18_REMEDIATION_REPORT.md"
    assert "independent review" in m18["unresolved_gap"].lower()
    assert '"M18"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m25_matrix_points_to_isolated_public_archive_downloader():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m25 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M25")
    assert m25["implementation_status"] == "TESTED"
    assert "trading_platform/v391/network_segmentation.py" in m25["code_reference"]
    assert "trading_platform/data/binance_public_data.py" in m25["code_reference"]
    assert "tests/test_binance_public_data_import.py" in m25["test_reference"]
    assert "tests/v391/test_network_segmentation.py" in m25["test_reference"]
    assert m25["evidence_reference"] == "V429_M25_PUBLIC_DATA_REPORT.md"
    assert "Infrastructure" in m25["unresolved_gap"]
    assert '"M25"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")


def test_v429_m11_matrix_points_to_durable_retry_replay_boundary():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        m11 = next(row for row in csv.DictReader(stream) if row["machine_check_id"] == "M11")
    assert m11["implementation_status"] == "TESTED"
    assert "trading_platform/v311/dispatch_guard.py" in m11["code_reference"]
    assert "trading_platform/v312/execution_runtime.py" in m11["code_reference"]
    assert "tests/v321/test_durable_dispatch.py" in m11["test_reference"]
    assert "tests/v312/test_execution_runtime.py" in m11["test_reference"]
    assert m11["evidence_reference"] == "V429_M11_REMEDIATION_REPORT.md"
    assert "venue" in m11["unresolved_gap"].lower()
    assert '"M11"' in (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")

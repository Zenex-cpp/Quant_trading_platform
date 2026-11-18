from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.contracts.causal_chain import CausalChainError, CausalChainRegistry
from trading_platform.contracts.causal_chain import CausalArtifact
from trading_platform.core.ttl_policy import TTLPolicyError, TTLPolicyRegistry
from trading_platform.gates.dependency_matrix import GateDependencyError, GateDependencyMatrix
from trading_platform.research.registry import StatisticalMethodCatalog, StatisticalMethodCatalogError
from trading_platform.risk.state_model import RiskStateModel, RiskStateModelError
from trading_platform.v318.durable_decision import RiskSystemState
from scripts.run_milestone_validation_v429 import CONTRACT_FILES


ROOT = Path(__file__).resolve().parents[1]


def test_milestone_contract_inputs_are_unique_and_present():
    assert len(CONTRACT_FILES) == len(set(CONTRACT_FILES))
    assert all((ROOT / name).is_file() for name in CONTRACT_FILES)


def test_risk_state_catalog_matches_durable_authority_and_fails_closed():
    model = RiskStateModel.from_csv(ROOT / "schemas/v5_risk_state_model.csv")
    assert tuple(item.state for item in model.definitions) == tuple(RiskSystemState)
    assert tuple(item.risk_factor for item in model.definitions) == (
        Decimal("1"), Decimal("0.75"), Decimal("0.50"), Decimal("0"), Decimal("0"), Decimal("0")
    )
    assert model.maximum_new_risk(RiskSystemState.ELEVATED, Decimal("100")) == Decimal("75.00")
    model.assert_new_risk_allowed(RiskSystemState.ELEVATED, Decimal("75"), Decimal("100"))
    with pytest.raises(RiskStateModelError, match="RISK_STATE_NEW_RISK_BLOCKED"):
        model.assert_new_risk_allowed(RiskSystemState.RECOVERY, Decimal("1"), Decimal("100"))
    with pytest.raises(RiskStateModelError, match="RISK_STATE_NEW_RISK_EXCEEDS_STATE_CAP"):
        model.assert_new_risk_allowed(RiskSystemState.ELEVATED, Decimal("76"), Decimal("100"))
    with pytest.raises(RiskStateModelError, match="RISK_STATE_NOT_REGISTERED"):
        model.definition("UNKNOWN")


def test_ttl_policy_covers_all_prompt_decision_classes_and_expiry_precedence():
    registry = TTLPolicyRegistry.from_csv(ROOT / "schemas/v5_decision_ttl_policy.csv")
    assert [item.decision_class for item in registry.policies] == [
        "Prediction", "Signal", "Opportunity Score", "Portfolio Allocation Decision", "Risk Decision", "Order Intent"
    ]
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    registry.assert_window("Risk Decision", now - timedelta(seconds=1), now + timedelta(seconds=1), now)
    with pytest.raises(TTLPolicyError, match="TTL_EXPIRED_OR_NOT_YET_VALID"):
        registry.assert_window("Risk Decision", now - timedelta(seconds=2), now - timedelta(seconds=1), now)
    with pytest.raises(TTLPolicyError, match="TTL_DOWNSTREAM_OUTLIVES_UPSTREAM"):
        registry.assert_downstream_not_longer(downstream_expires_at=now + timedelta(seconds=2), upstream_expires_at=now + timedelta(seconds=1))
    with pytest.raises(TTLPolicyError, match="TTL_POLICY_COVERAGE_INVALID"):
        TTLPolicyRegistry(registry.policies[:-1])


def test_causal_chain_is_complete_and_rejects_missing_upstream_or_fields():
    registry = CausalChainRegistry.from_csv(ROOT / "schemas/v5_causal_artifact_chain.csv")
    assert len(registry.nodes) == 13
    assert registry.nodes[0].artifact_type == "Prediction"
    assert registry.nodes[-1].artifact_type == "P&L"

    def artifact(
        artifact_type: str,
        artifact_id: str,
        timestamp: int,
        expires: int,
        dependencies: tuple[str, ...] = (),
    ) -> CausalArtifact:
        return CausalArtifact(artifact_type, {
            "artifact_id": artifact_id,
            "version": "1",
            "timestamp_ms": timestamp,
            "valid_from_ms": 0,
            "expires_at_ms": expires,
            "state": "VALID",
            "provenance_id": "prov-" + artifact_id,
            "fingerprint": "sha256-" + artifact_id,
            "dependency_ids": list(dependencies),
        })

    upstream = [
        artifact("Prediction", "prediction-1", 10, 200),
        artifact("Signal", "signal-1", 20, 180, ("prediction-1",)),
        artifact("Opportunity", "opportunity-1", 30, 160, ("signal-1",)),
        artifact("Portfolio Decision", "portfolio-1", 40, 140, ("opportunity-1",)),
    ]
    risk = artifact("Risk Decision", "risk-1", 50, 120, ("portfolio-1",))
    registry.validate_artifact("Risk Decision", risk.payload, upstream, now_ms=100)
    with pytest.raises(CausalChainError, match="CAUSAL_REQUIRED_UPSTREAM_MISSING"):
        registry.validate_artifact("Order Intent", artifact("Order Intent", "intent-1", 60, 120, ("missing",)).payload, upstream, now_ms=100)
    with pytest.raises(CausalChainError, match="CAUSAL_DOWNSTREAM_OUTLIVES_UPSTREAM"):
        registry.validate_artifact("Risk Decision", artifact("Risk Decision", "risk-2", 50, 150, ("portfolio-1",)).payload, upstream, now_ms=100)
    stale = [artifact("Prediction", "prediction-stale", 10, 90)]
    with pytest.raises(CausalChainError, match="CAUSAL_ARTIFACT_EXPIRED_OR_FUTURE"):
        registry.validate_artifact("Signal", artifact("Signal", "signal-stale", 20, 80, ("prediction-stale",)).payload, stale, now_ms=100)
    with pytest.raises(CausalChainError, match="CAUSAL_REQUIRED_UPSTREAM_MISMATCH"):
        registry.validate_artifact("Order Intent", artifact("Order Intent", "intent-2", 60, 120, ("prediction-1",)).payload, upstream, now_ms=100)
    with pytest.raises(CausalChainError, match="CAUSAL_REQUIRED_FIELDS_MISSING"):
        registry.validate_artifact("Prediction", {"artifact_id": "prediction-invalid"}, (), now_ms=100)


def test_statistical_method_catalog_is_versioned_and_specification_only():
    catalog = StatisticalMethodCatalog.from_csv(ROOT / "schemas/v5_statistical_method_registry.csv")
    assert len(catalog.specs) == 18
    assert len({(item.method_id, item.version) for item in catalog.specs}) == len(catalog.specs)
    for item in catalog.specs:
        assert (ROOT / item.implementation_reference).is_file()
    assert catalog.get("BRIER_SCORE", "1.0").required_inputs
    assert "implementation_not_present" in catalog.get("DEFLATED_SHARPE_SPECIFICATION", "1.0").limitations
    with pytest.raises(StatisticalMethodCatalogError, match="METHOD_NOT_REGISTERED"):
        catalog.get("MISSING", "1")


def test_gate_dependency_matrix_is_acyclic_and_fail_closed():
    matrix = GateDependencyMatrix.from_csv(ROOT / "schemas/v5_gate_dependency_matrix.csv")
    matrix.assert_satisfied("LIVE_ACTIVATION", {
        "DATA_QUALITY", "SPLIT_INTEGRITY", "MODEL_COMPATIBILITY", "EVIDENCE_VALIDITY",
        "ARTIFACT_INTEGRITY", "RECONCILIATION", "RISK_DECISION", "RECOVERY_PROOF", "PROMOTION", "LIVE_ACTIVATION",
    }, {
        "dataset_contract", "quality_report", "split_spec", "purge_report", "model_artifact",
        "compatibility_report", "evidence_snapshot", "dependency_checkpoint", "artifact_manifest",
        "integrity_authorization", "reconciliation_snapshot", "accounting_projection", "risk_decision",
        "risk_reservation", "recovery_proof", "invariants", "guards", "promotion_bundle", "approval",
        "scope", "activation_authority", "kill_switch", "venue_policy",
    })
    with pytest.raises(GateDependencyError, match="GATE_DEPENDENCY_NOT_SATISFIED"):
        matrix.assert_satisfied("PROMOTION", {"MODEL_COMPATIBILITY"}, set())
    with pytest.raises(GateDependencyError, match="GATE_ARTIFACT_NOT_SATISFIED"):
        matrix.assert_satisfied("LIVE_ACTIVATION", {
            "DATA_QUALITY", "SPLIT_INTEGRITY", "MODEL_COMPATIBILITY", "EVIDENCE_VALIDITY",
            "ARTIFACT_INTEGRITY", "RECONCILIATION", "RISK_DECISION", "RECOVERY_PROOF", "PROMOTION", "LIVE_ACTIVATION",
        }, set())


def test_recovery_and_dr_catalogs_cover_required_controls():
    for name, required in (
        ("v5_recovery_restart_plan.csv", {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}),
        ("v5_disaster_recovery_plan.csv", {"DR-STATE", "DR-EVIDENCE", "DR-CONFIG", "DR-RECOVERY"}),
    ):
        with (ROOT / "schemas" / name).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        identifier_column = "step_id" if name == "v5_recovery_restart_plan.csv" else "control_id"
        assert {row[identifier_column] for row in rows} == required
        assert all(all(value.strip() for value in row.values()) for row in rows)
    recovery = (ROOT / "docs/77_V5_RECOVERY_RESTART_PLAN.md").read_text(encoding="utf-8")
    disaster = (ROOT / "docs/78_V5_DISASTER_RECOVERY_PLAN.md").read_text(encoding="utf-8")
    assert "lower-layer recovery cannot bypass" in recovery
    assert "RPO/RTO" in disaster

from __future__ import annotations

import copy
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v417.production_readiness_compliance import (
    MANDATORY_REQUIREMENTS_V417,
    ProductionReadinessComplianceAuthorityV417,
    ProductionReadinessComplianceErrorV417,
)

NOW = 1_800_001_000_000


def _matrix(*, verified: bool) -> list[dict[str, str]]:
    rows = []
    for rid, text in MANDATORY_REQUIREMENTS_V417:
        rows.append({
            "requirement_id": rid,
            "requirement_text": text,
            "priority": "CRITICAL",
            "implementation_status": "VERIFIED" if verified else "TESTED",
            "code_reference": f"src/{rid}",
            "schema_reference": f"schemas/{rid}.csv",
            "test_reference": f"tests/{rid}.py",
            "evidence_reference": f"evidence://{rid}",
            "owner": "governance",
            "unresolved_gap": "" if verified else "external evidence remains NOT_VERIFIED",
        })
    return rows


def _convergence(store: EventStore):
    store.append(
        event_id="operational-readiness-convergence-v416:CONV-417",
        occurred_at_ms=NOW,
        event_type="OPERATIONAL_READINESS_CONVERGED_V416",
        aggregate_id="BUNDLE-417",
        payload={"status": "VERIFIED", "bundle_id": "BUNDLE-417", "activation_flag": "NOT_SET"},
    )


def test_missing_convergence_blocks():
    with pytest.raises(ProductionReadinessComplianceErrorV417, match="OPERATIONAL_CONVERGENCE_REQUIRED"):
        ProductionReadinessComplianceAuthorityV417(EventStore()).evaluate(
            decision_id="DEC-417", convergence_id="MISSING", matrix=_matrix(verified=False), now_ms=NOW
        )


def test_current_matrix_is_blocked_by_unverified_operational_requirements():
    store = EventStore(); _convergence(store)
    d = ProductionReadinessComplianceAuthorityV417(store).evaluate(
        decision_id="DEC-417-BLOCKED", convergence_id="CONV-417", matrix=_matrix(verified=False), now_ms=NOW
    )
    assert not d.allowed
    assert d.status == "BLOCKED"
    assert len(d.blocking_requirement_ids) == len(MANDATORY_REQUIREMENTS_V417)
    assert d.blocking_requirement_ids[0] == "MP174-01"
    event = ProductionReadinessComplianceAuthorityV417(store).get("DEC-417-BLOCKED")
    assert event.payload["production_ready"] is False


def test_fully_verified_matrix_is_contract_verified_but_no_runtime_activation():
    store = EventStore(); _convergence(store)
    authority = ProductionReadinessComplianceAuthorityV417(store)
    d = authority.evaluate(
        decision_id="DEC-417-VERIFIED", convergence_id="CONV-417", matrix=_matrix(verified=True), now_ms=NOW
    )
    assert d.allowed and d.status == "VERIFIED"
    authority.assert_valid("DEC-417-VERIFIED")
    event = authority.get("DEC-417-VERIFIED")
    assert event.payload["production_ready"] is False
    assert event.payload["activation_flag"] == "NOT_SET"


def test_duplicate_requirement_is_rejected():
    store = EventStore(); _convergence(store)
    matrix = _matrix(verified=False)
    matrix.append(copy.deepcopy(matrix[0]))
    with pytest.raises(ProductionReadinessComplianceErrorV417, match="COMPLIANCE_DUPLICATE_REQUIREMENT:MP174-01"):
        ProductionReadinessComplianceAuthorityV417(store).evaluate(
            decision_id="DEC-417-DUP", convergence_id="CONV-417", matrix=matrix, now_ms=NOW
        )


def test_missing_reference_blocks_even_if_status_says_verified():
    store = EventStore(); _convergence(store)
    matrix = _matrix(verified=True)
    matrix[0]["evidence_reference"] = ""
    d = ProductionReadinessComplianceAuthorityV417(store).evaluate(
        decision_id="DEC-417-REF", convergence_id="CONV-417", matrix=matrix, now_ms=NOW
    )
    assert not d.allowed
    assert d.blocking_requirement_ids == ("MP174-01",)


def test_matrix_mutation_rejects_same_decision_id():
    store = EventStore(); _convergence(store)
    authority = ProductionReadinessComplianceAuthorityV417(store)
    matrix = _matrix(verified=True)
    authority.evaluate(decision_id="DEC-417-IDEMP", convergence_id="CONV-417", matrix=matrix, now_ms=NOW)
    matrix[1]["unresolved_gap"] = "changed"
    with pytest.raises(ProductionReadinessComplianceErrorV417, match="COMPLIANCE_DECISION_ID_CONFLICT"):
        authority.evaluate(decision_id="DEC-417-IDEMP", convergence_id="CONV-417", matrix=matrix, now_ms=NOW)

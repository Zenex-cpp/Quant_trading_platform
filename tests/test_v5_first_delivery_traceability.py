from __future__ import annotations

import csv
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v5_first_delivery_register_covers_all_prompt_items_and_real_paths():
    with (ROOT / "schemas/v5_first_delivery_traceability.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 55
    assert [row["item_id"] for row in rows] == [f"FD-{i:02d}" for i in range(1, 56)]
    assert {row["status"] for row in rows} <= {"PRESENT", "PARTIAL", "OPEN"}
    assert sum(row["status"] == "PRESENT" for row in rows) == 40
    assert sum(row["status"] == "PARTIAL" for row in rows) == 15
    assert sum(row["status"] == "OPEN" for row in rows) == 0
    for row in rows:
        references = [
            value
            for column in ("primary_reference", "implementation_reference")
            for value in row[column].split(";")
            if value
        ]
        assert all((ROOT / reference).is_file() for reference in references), row["item_id"]
        if row["status"] in {"PARTIAL", "OPEN"}:
            assert row["remaining_gap"].strip(), row["item_id"]


def test_v5_traceability_document_states_the_non_operational_acceptance_boundary():
    document = (ROOT / "docs/60_V5_FIRST_DELIVERY_TRACEABILITY.md").read_text(encoding="utf-8")
    assert "55" in document
    assert "do not certify external review" in document
    assert "Source code alone is not sufficient" in document


def test_v5_safety_and_research_registries_are_complete_and_fail_closed():
    def rows(name: str) -> list[dict[str, str]]:
        with (ROOT / "schemas" / name).open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    errors = rows("v5_error_taxonomy.csv")
    assert errors
    assert len({row["error_code"] for row in errors}) == len(errors)
    assert all(row["severity_default"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW"} for row in errors)
    assert all(row["default_response"] for row in errors)

    fail_safe = rows("v5_fail_safe_matrix.csv")
    assert all(all(value for value in row.values()) for row in fail_safe)
    by_failure = {row["failure_class"]: row for row in fail_safe}
    assert by_failure["SECURITY_OR_TRUST"]["new_entry"] == "BLOCK"
    assert by_failure["SECURITY_OR_TRUST"]["deploy"] == "BLOCK"
    assert by_failure["RECOVERY_UNVERIFIED"]["new_entry"] == "BLOCK"
    assert by_failure["RECOVERY_UNVERIFIED"]["recovery"] == "BLOCK"

    precedence = rows("v5_failure_precedence.csv")
    assert [int(row["precedence"]) for row in precedence] == list(range(1, 8))
    assert precedence[0]["failure_class"] == "SECURITY"
    assert precedence[-1]["failure_class"] == "PERFORMANCE"

    incidents = rows("v5_incident_severity_scope.csv")
    severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    scopes = {"INSTRUMENT", "STRATEGY", "PORTFOLIO", "SYSTEM"}
    assert {(row["severity"], row["scope"]) for row in incidents} == set(product(severities, scopes))
    assert all(row["containment"] and row["required_response"] and row["resume_condition"] for row in incidents)

    for filename, id_column in (
        ("v5_metric_applicability_registry.csv", "metric_id"),
        ("v5_objective_function_registry.csv", "objective_id"),
        ("v5_benchmark_registry.csv", "benchmark_id"),
    ):
        registry = rows(filename)
        identifiers = [row[id_column] for row in registry]
        assert identifiers and len(identifiers) == len(set(identifiers))
        assert all(row["maturity"] == "SPECIFICATION_ONLY" for row in registry)

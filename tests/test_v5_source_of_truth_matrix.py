from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOMAINS = {
    "SPECIFICATION", "RUNTIME_SOURCE", "PACKAGE_RELEASE", "CONFIGURATION",
    "RAW_MARKET_DATA", "NORMALIZED_DATASET", "FEATURES_AND_PREDICTIONS",
    "MODEL_ARTIFACT", "EVENT_HISTORY", "RESEARCH_RUN", "EVIDENCE_SNAPSHOT",
    "GATE_RESULT", "CHAMPION", "PROMOTION_BUNDLE", "DEPLOYMENT",
    "ORDER_INTENT", "VENUE_ORDER_AND_FILL", "POSITION", "ACCOUNTING",
    "RISK_BUDGET", "CREDENTIAL_SECRET", "ACTOR_AND_REVIEWER_IDENTITY",
    "TIME_SOURCE", "GITHUB_BRANCH_AND_CI", "MILESTONE_VERIFICATION",
}
STATUSES = {
    "CANONICAL_SPECIFICATION", "CANONICAL_SOURCE", "DURABLE_IF_CONFIGURED",
    "PARTIAL", "EXTERNAL_REQUIRED",
}
REQUIRED_COLUMNS = {
    "domain_id", "authoritative_record", "canonical_source",
    "identity_version_binding", "derived_or_cached_records", "conflict_action",
    "status", "operational_boundary", "references",
}


def test_v5_source_of_truth_matrix_is_complete_and_references_real_repository_files():
    with (ROOT / "schemas/v5_source_of_truth_matrix.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        reader = csv.DictReader(stream)
        assert set(reader.fieldnames or ()) == REQUIRED_COLUMNS
        rows = list(reader)

    assert len(rows) == len(EXPECTED_DOMAINS)
    assert {row["domain_id"] for row in rows} == EXPECTED_DOMAINS
    assert len({row["domain_id"] for row in rows}) == len(rows)
    assert all(row["status"] in STATUSES for row in rows)

    for row in rows:
        assert all(row[column].strip() for column in REQUIRED_COLUMNS), row["domain_id"]
        references = [value for value in row["references"].split(";") if value]
        assert references, row["domain_id"]
        assert all((ROOT / reference).is_file() for reference in references), row["domain_id"]


def test_v5_source_of_truth_matrix_keeps_conflicts_and_external_boundaries_fail_closed():
    with (ROOT / "schemas/v5_source_of_truth_matrix.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = {row["domain_id"]: row for row in csv.DictReader(stream)}

    assert "CONFIG_CONFLICT" in rows["CONFIGURATION"]["conflict_action"]
    assert "UNKNOWN" in rows["POSITION"]["conflict_action"]
    assert "UNKNOWN" in rows["ACCOUNTING"]["conflict_action"]
    assert rows["RAW_MARKET_DATA"]["status"] == "EXTERNAL_REQUIRED"
    assert rows["ACTOR_AND_REVIEWER_IDENTITY"]["status"] == "EXTERNAL_REQUIRED"
    assert rows["GITHUB_BRANCH_AND_CI"]["status"] == "EXTERNAL_REQUIRED"

    document = (ROOT / "docs/70_V5_SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
    assert "Authority is domain-scoped" in document
    assert "does not assert that an external source is connected" in document
    assert "never resolve a disagreement by picking whichever value is newest" in document

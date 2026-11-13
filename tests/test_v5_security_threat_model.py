from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT_THREATS = {
    "COMPROMISED_RESEARCH_AGENT",
    "COMPROMISED_MODEL",
    "DEPENDENCY_COMPROMISE",
    "CREDENTIAL_LEAK",
    "CONFIG_TAMPERING",
    "DUPLICATE_ORDERS",
    "REPLAY",
    "UNAUTHORIZED_DEPLOYMENT",
    "AUDIT_TAMPERING",
    "SUPPLY_CHAIN_ATTACK",
}


def test_v5_threat_model_covers_every_prompt_threat_with_complete_actions():
    with (ROOT / "schemas/v5_threat_model.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert {row["threat"] for row in rows} == PROMPT_THREATS
    assert len(rows) == len(PROMPT_THREATS)
    assert len({row["threat_id"] for row in rows}) == len(rows)
    required = {
        "threat_actor",
        "target_assets",
        "attack_path",
        "prevention",
        "detection",
        "remediation",
        "owner",
        "control_status",
        "residual_risk",
        "control_evidence",
    }
    for row in rows:
        assert all(row[field].strip() for field in required), row["threat"]
        assert row["control_status"] in {"BOUNDED_CODE_TESTED", "PARTIAL"}
        evidence_paths = row["control_evidence"].split(";")
        assert all((ROOT / path).is_file() for path in evidence_paths), row["threat"]


def test_v5_threat_model_explains_residual_and_external_review_boundary():
    document = (ROOT / "docs/65_V5_SECURITY_THREAT_MODEL.md").read_text(
        encoding="utf-8"
    )
    assert "ten threat classes" in document
    assert "prevention, detection, remediation, and a responsible owner" in document
    assert "independent penetration test" in document
    assert "does not assert that every listed control is deployed" in document

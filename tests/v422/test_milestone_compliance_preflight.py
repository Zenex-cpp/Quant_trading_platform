from __future__ import annotations
import csv
from pathlib import Path

import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v422.milestone_compliance_preflight import (
    MilestoneCompliancePreflightAuthorityV422,
    MilestonePreflightErrorV422,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_850_000_000_000
BASELINE_SHA = "a" * 64
HASHES = {"matrix": "b" * 64, "workflow": "c" * 64}


def matrix_rows():
    with (ROOT / "compliance_v424.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_v422_preflight_records_ready_for_tested_nonblocked_requirement():
    store = EventStore()
    authority = MilestoneCompliancePreflightAuthorityV422(store)
    decision = authority.evaluate(
        decision_id="preflight-ready", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
        baseline_sha256=BASELINE_SHA, rows=matrix_rows(), impacted_ids=["CI-PREFLIGHT-01"],
        input_hashes=HASHES, now_ms=NOW,
    )
    assert decision.allowed is True
    assert decision.status == "READY_FOR_MILESTONE"
    assert decision.duplicate is False
    assert store.verify_chain()
    duplicate = authority.evaluate(
        decision_id="preflight-ready", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
        baseline_sha256=BASELINE_SHA, rows=matrix_rows(), impacted_ids=["CI-PREFLIGHT-01"],
        input_hashes=HASHES, now_ms=NOW + 100,
    )
    assert duplicate.duplicate is True
    assert duplicate.event_hash == decision.event_hash


def test_v422_impacted_blocked_row_prevents_dispatch():
    rows = matrix_rows()
    row = next(r for r in rows if r["machine_check_id"] == "CI-PREFLIGHT-01")
    row["implementation_status"] = "BLOCKED"
    store = EventStore()
    decision = MilestoneCompliancePreflightAuthorityV422(store).evaluate(
        decision_id="preflight-blocked", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
        baseline_sha256=BASELINE_SHA, rows=rows, impacted_ids=["CI-PREFLIGHT-01"],
        input_hashes=HASHES, now_ms=NOW,
    )
    assert not decision.allowed
    assert decision.status == "BLOCKED"
    assert "IMPACTED_REQUIREMENT_BLOCKED:CI-PREFLIGHT-01" in decision.blockers


def test_v422_rejects_missing_mandatory_row_and_bad_hash():
    rows = [r for r in matrix_rows() if r["machine_check_id"] != "M30"]
    with pytest.raises(MilestonePreflightErrorV422, match="MANDATORY_M_CHECKS_MISSING:M30"):
        MilestoneCompliancePreflightAuthorityV422().evaluate(
            decision_id="missing-row", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
            baseline_sha256=BASELINE_SHA, rows=rows, impacted_ids=["CI-PREFLIGHT-01"], input_hashes=HASHES, now_ms=NOW,
        )
    with pytest.raises(MilestonePreflightErrorV422, match="BASELINE_SHA256_INVALID"):
        MilestoneCompliancePreflightAuthorityV422().evaluate(
            decision_id="bad-hash", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
            baseline_sha256="bad", rows=matrix_rows(), impacted_ids=["CI-PREFLIGHT-01"], input_hashes=HASHES, now_ms=NOW,
        )


def test_v422_assert_current_rejects_matrix_drift():
    store = EventStore()
    authority = MilestoneCompliancePreflightAuthorityV422(store)
    rows = matrix_rows()
    authority.evaluate(
        decision_id="preflight-drift", milestone_id="V4.24", baseline_version="V4.18-RECOVERY",
        baseline_sha256=BASELINE_SHA, rows=rows, impacted_ids=["CI-PREFLIGHT-01"], input_hashes=HASHES, now_ms=NOW,
    )
    rows[0]["unresolved_gap"] = "changed after preflight"
    with pytest.raises(MilestonePreflightErrorV422, match="PREFLIGHT_STALE:MATRIX_HASH"):
        authority.assert_current("preflight-drift", rows=rows, baseline_version="V4.18-RECOVERY", baseline_sha256=BASELINE_SHA, input_hashes=HASHES)

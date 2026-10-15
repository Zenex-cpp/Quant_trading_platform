from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_v407_source_contract():
    source = (ROOT / "src/trading_platform/v407/critical_promotion_evidence.py").read_text(encoding="utf-8")
    for token in (
        "EVIDENCE_SNAPSHOT_FRESH_AND_BOUND",
        "EVIDENCE_SNAPSHOT_AUTHORITY_NOT_FOUND",
        "EVENT_CHAIN_INVALID",
        "SHARED_EVENT_STORE_REQUIRED",
        "EvidenceSnapshotAuthorityLedger",
    ):
        assert token in source

def test_v407_package_docs_exist():
    for name in ("V407_RELEASE_NOTES.md", "V407_VERIFICATION_REPORT.md", "V407_OPEN_GAPS_DELTA.md", "V407_CHANGE_IMPACT.md", "compliance_v407.csv"):
        assert (ROOT / name).exists()

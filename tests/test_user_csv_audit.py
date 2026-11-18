from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone

import pytest

from trading_platform.cli import main
from trading_platform.data.user_csv_audit import (
    UserCsvAuditError,
    audit_user_dataset_csv,
)

UTC = timezone.utc
VALID_CSV = (
    "event_time,symbol,open,high,low,close,volume,venue\n"
    "2026-01-01T00:00:00Z,BTCUSDT,100,110,90,105,5,spot\n"
    "2026-01-01T00:01:00Z,BTCUSDT,105,112,100,111,3,spot\n"
)


def _source(tmp_path, text: str = VALID_CSV):
    source = tmp_path / "market.csv"
    source.write_text(text, encoding="utf-8", newline="")
    return source


def test_audits_user_csv_into_dataset_contract_without_network_or_copy(tmp_path, monkeypatch):
    source = _source(tmp_path)

    def deny_network(*args, **kwargs):
        raise AssertionError("USER_CSV_AUDIT_ATTEMPTED_NETWORK_ACCESS")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    result = audit_user_dataset_csv(
        input_path=source,
        source_label="User supplied CSV",
        report_path=tmp_path / "audit.json",
        anomaly_note="No known anomalies reported by operator.",
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    contract = result.dataset_contract
    assert result.exit_code == 0
    assert result.row_count == 2
    assert contract is not None
    assert contract.dataset_id == "DATASET-01"
    assert contract.quality_status.value == "VALID"
    assert contract.coverage_start == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert contract.coverage_end == datetime(2026, 1, 1, 0, 1, tzinfo=UTC) + timedelta(milliseconds=1)
    assert contract.lineage[0] == "file:market.csv"
    assert report["source_file"]["copied"] is False
    assert report["source_license_assessment"] == "NOT_ASSESSED"
    assert report["source_comparison"]["status"] == "NOT_PERFORMED_SINGLE_SOURCE"
    assert report["dataset_authority"] == "NOT_AUTHORIZED_BY_SINGLE_SOURCE_AUDIT"
    assert report["temporal_validation"]["status"] == "PASS"
    assert report["anomaly_documentation"]["status"] == "DOCUMENTED"
    assert report["network_used"] is False
    assert b"2026-01-01T00:00:00Z" not in (tmp_path / "audit.json").read_bytes()


def test_missing_required_values_are_critical_but_report_is_preserved(tmp_path):
    source = _source(
        tmp_path,
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,BTCUSDT,100,110,90,105,\n",
    )
    report_path = tmp_path / "critical.json"

    result = audit_user_dataset_csv(
        input_path=source,
        source_label="Vendor A",
        report_path=report_path,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.exit_code == 1
    assert result.quality_status.value == "CRITICAL"
    assert result.dataset_contract is not None
    assert "REQUIRED_VALUE_MISSING" in report["quality_report"]["findings"]


def test_unparseable_or_naive_times_do_not_create_coverage_contract(tmp_path):
    source = _source(
        tmp_path,
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:00:00,BTCUSDT,100,110,90,105,5\n",
    )

    result = audit_user_dataset_csv(
        input_path=source,
        source_label="Vendor A",
        report_path=tmp_path / "temporal.json",
    )

    report = json.loads((tmp_path / "temporal.json").read_text(encoding="utf-8"))
    assert result.exit_code == 1
    assert result.dataset_contract is None
    assert report["temporal_validation"]["timezone_aware"] is False
    assert report["temporal_validation"]["status"] == "REVIEW_REQUIRED"


def test_report_is_exclusive_and_never_overwrites_existing_file(tmp_path):
    source = _source(tmp_path)
    report_path = tmp_path / "audit.json"
    audit_user_dataset_csv(input_path=source, source_label="Vendor A", report_path=report_path)
    original = report_path.read_bytes()

    with pytest.raises(FileExistsError):
        audit_user_dataset_csv(input_path=source, source_label="Vendor A", report_path=report_path)

    assert report_path.read_bytes() == original


def test_report_cannot_be_written_in_repository_or_over_source(tmp_path):
    source = _source(tmp_path)
    with pytest.raises(UserCsvAuditError, match="REPORT_INSIDE_REPOSITORY"):
        audit_user_dataset_csv(
            input_path=source,
            source_label="Vendor A",
            report_path="DATASET-01-audit.json",
        )
    with pytest.raises(UserCsvAuditError, match="REPORT_EQUALS_SOURCE"):
        audit_user_dataset_csv(
            input_path=source,
            source_label="Vendor A",
            report_path=source,
        )


def test_invalid_csv_header_is_rejected_without_report(tmp_path):
    source = _source(tmp_path, "event_time,symbol,close\n2026-01-01T00:00:00Z,BTCUSDT,105\n")
    report_path = tmp_path / "invalid.json"

    with pytest.raises(UserCsvAuditError, match="REQUIRED_COLUMNS_MISSING"):
        audit_user_dataset_csv(input_path=source, source_label="Vendor A", report_path=report_path)

    assert not report_path.exists()


def test_market_data_audit_csv_cli_prints_local_audit_summary(tmp_path, capsys, monkeypatch):
    source = _source(tmp_path)

    def deny_network(*args, **kwargs):
        raise AssertionError("USER_CSV_AUDIT_CLI_ATTEMPTED_NETWORK_ACCESS")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    report_path = tmp_path / "cli-audit.json"

    exit_code = main([
        "market-data", "audit-csv",
        "--input", str(source),
        "--source-label", "User supplied CSV",
        "--report", str(report_path),
        "--anomaly-note", "No known anomalies reported by operator.",
    ])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["status"] == "AUDITED"
    assert summary["review_required"] is False
    assert summary["dataset_contract_created"] is True
    assert summary["source_comparison"] == "NOT_PERFORMED_SINGLE_SOURCE"
    assert summary["network_used"] is False
    assert summary["report_written"] is True
    assert report_path.is_file()


def test_two_source_comparison_matches_utc_keys_and_records_both_contracts(tmp_path):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T01:01:00+01:00,BTCUSDT,105,112,100,111,3\n"
        "2026-01-01T01:00:00+01:00,BTCUSDT,100,110,90,105,5\n",
        encoding="utf-8",
        newline="",
    )

    result = audit_user_dataset_csv(
        input_path=primary,
        source_label="Vendor A",
        report_path=tmp_path / "comparison.json",
        comparison_input_path=comparison,
        comparison_source_label="Vendor B",
    )

    report = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    comparison_result = report["source_comparison"]
    assert result.exit_code == 1
    assert result.source_comparison_status == "MATCH"
    assert comparison_result["comparison_quality_report"]["out_of_order"] is True
    assert comparison_result["status"] == "COMPLETED"
    assert comparison_result["agreement"] == "MATCH"
    assert comparison_result["matched_key_count"] == 2
    assert comparison_result["divergent_row_count"] == 0
    assert comparison_result["field_difference_counts"] == {
        "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0,
    }
    assert len(comparison_result["sources"]) == 2
    assert report["comparison_dataset_contract"]["dataset_id"] == "DATASET-01-COMPARE"
    assert comparison_result["source_independence"] == "NOT_VERIFIED"
    assert report["dataset_authority"] == "NOT_AUTHORIZED_BY_LOCAL_SOURCE_COMPARISON"


def test_source_comparison_reports_value_and_coverage_differences(tmp_path):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,BTCUSDT,101,110,90,105,5\n",
        encoding="utf-8",
        newline="",
    )

    result = audit_user_dataset_csv(
        input_path=primary,
        source_label="Vendor A",
        report_path=tmp_path / "divergence.json",
        comparison_input_path=comparison,
        comparison_source_label="Vendor B",
    )

    report = json.loads((tmp_path / "divergence.json").read_text(encoding="utf-8"))
    comparison_result = report["source_comparison"]
    assert result.exit_code == 1
    assert result.source_comparison_status == "REVIEW_REQUIRED"
    assert comparison_result["agreement"] == "REVIEW_REQUIRED"
    assert comparison_result["matched_key_count"] == 1
    assert comparison_result["primary_only_key_count"] == 1
    assert comparison_result["comparison_only_key_count"] == 0
    assert comparison_result["divergent_row_count"] == 1
    assert comparison_result["field_difference_counts"]["open"] == 1


def test_source_comparison_blocks_duplicate_utc_symbol_keys(tmp_path):
    primary = _source(
        tmp_path,
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,BTCUSDT,100,110,90,105,5\n"
        "2026-01-01T01:00:00+01:00,BTCUSDT,100,110,90,105,5\n",
    )
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(VALID_CSV, encoding="utf-8", newline="")

    result = audit_user_dataset_csv(
        input_path=primary,
        source_label="Vendor A",
        report_path=tmp_path / "duplicate.json",
        comparison_input_path=comparison,
        comparison_source_label="Vendor B",
    )

    report = json.loads((tmp_path / "duplicate.json").read_text(encoding="utf-8"))
    assert result.exit_code == 1
    assert result.source_comparison_status == "NOT_ASSESSED"
    assert report["source_comparison"]["status"] == "INCOMPARABLE"
    assert report["source_comparison"]["reasons"] == ["DATASET_COMPARISON_DUPLICATE_UTC_SYMBOL_KEY"]


def test_source_comparison_applies_explicit_decimal_tolerances(tmp_path):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,BTCUSDT,100.05,110,90,105,5\n"
        "2026-01-01T00:01:00Z,BTCUSDT,105,112,100,111,3\n",
        encoding="utf-8",
        newline="",
    )

    result = audit_user_dataset_csv(
        input_path=primary,
        source_label="Vendor A",
        report_path=tmp_path / "tolerance.json",
        comparison_input_path=comparison,
        comparison_source_label="Vendor B",
        relative_tolerance="0.001",
    )

    report = json.loads((tmp_path / "tolerance.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert report["source_comparison"]["agreement"] == "MATCH"
    assert report["source_comparison"]["field_difference_counts"]["open"] == 0
    assert report["source_comparison"]["tolerance"]["relative"] == "0.001"


def test_source_comparison_rejects_unbounded_tolerance(tmp_path):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(VALID_CSV, encoding="utf-8", newline="")

    with pytest.raises(UserCsvAuditError, match="ABSOLUTE_TOLERANCE_INVALID"):
        audit_user_dataset_csv(
            input_path=primary,
            source_label="Vendor A",
            report_path=tmp_path / "invalid-tolerance.json",
            comparison_input_path=comparison,
            comparison_source_label="Vendor B",
            absolute_tolerance="1e13",
        )

    assert not (tmp_path / "invalid-tolerance.json").exists()


def test_cli_accepts_two_source_comparison_options(tmp_path, capsys):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(VALID_CSV, encoding="utf-8", newline="")
    report_path = tmp_path / "cli-comparison.json"

    exit_code = main([
        "market-data", "audit-csv",
        "--input", str(primary),
        "--source-label", "Vendor A",
        "--compare-input", str(comparison),
        "--compare-source-label", "Vendor B",
        "--compare-anomaly-note", "Vendor B reported no known revisions.",
        "--report", str(report_path),
    ])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["source_comparison"] == "MATCH"
    assert summary["dataset_authority"] == "NOT_AUTHORIZED_BY_LOCAL_SOURCE_COMPARISON"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source_comparison"]["agreement"] == "MATCH"
    assert report["source_comparison"]["comparison_anomaly_documentation"]["status"] == "DOCUMENTED"


def test_comparison_match_with_out_of_order_source_still_requires_review(tmp_path):
    primary = _source(tmp_path)
    comparison = tmp_path / "vendor_b.csv"
    comparison.write_text(
        "event_time,symbol,open,high,low,close,volume\n"
        "2026-01-01T00:01:00Z,BTCUSDT,105,112,100,111,3\n"
        "2026-01-01T00:00:00Z,BTCUSDT,100,110,90,105,5\n",
        encoding="utf-8",
        newline="",
    )

    result = audit_user_dataset_csv(
        input_path=primary,
        source_label="Vendor A",
        report_path=tmp_path / "out-of-order.json",
        comparison_input_path=comparison,
        comparison_source_label="Vendor B",
    )

    report = json.loads((tmp_path / "out-of-order.json").read_text(encoding="utf-8"))
    assert report["source_comparison"]["agreement"] == "MATCH"
    assert report["source_comparison"]["comparison_quality_report"]["out_of_order"] is True
    assert result.exit_code == 1

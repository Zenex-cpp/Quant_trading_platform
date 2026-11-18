"""Bounded, local-only audit of a user/vendor OHLCV CSV for DATASET-01."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat

from trading_platform.data.dataset import DatasetAuditReport, audit_ohlcv
from trading_platform.data_v03 import DatasetContract, QualityStatus, canonical_json, content_hash

UTC = timezone.utc
REQUIRED_COLUMNS = ("event_time", "symbol", "open", "high", "low", "close", "volume")
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 250_000
MAX_REPORT_BYTES = 4 * 1024 * 1024
_DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class UserCsvAuditError(ValueError):
    """Raised when the source CSV or requested report path is unsafe/invalid."""


@dataclass(frozen=True)
class UserCsvAuditResult:
    report_path: Path
    dataset_contract: DatasetContract | None
    quality_status: QualityStatus
    row_count: int
    exit_code: int
    source_sha256: str
    source_comparison_status: str


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_stable_source(path: Path) -> bytes:
    if path.is_symlink():
        raise UserCsvAuditError("DATASET_CSV_SYMLINK_REJECTED")
    try:
        before_path = path.stat()
    except OSError as exc:
        raise UserCsvAuditError("DATASET_CSV_SOURCE_UNAVAILABLE") from exc
    if not stat.S_ISREG(before_path.st_mode):
        raise UserCsvAuditError("DATASET_CSV_SOURCE_NOT_REGULAR")
    if before_path.st_size < 1 or before_path.st_size > MAX_SOURCE_BYTES:
        raise UserCsvAuditError("DATASET_CSV_SOURCE_SIZE_INVALID")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UserCsvAuditError("DATASET_CSV_SOURCE_OPEN_FAILED") from exc
    try:
        before_fd = os.fstat(descriptor)
        if not stat.S_ISREG(before_fd.st_mode) or _stat_identity(before_fd) != _stat_identity(before_path):
            raise UserCsvAuditError("DATASET_CSV_SOURCE_CHANGED_BEFORE_READ")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            body = source.read(MAX_SOURCE_BYTES + 1)
        after_fd = os.fstat(descriptor)
        after_path = path.stat()
        if (
            len(body) > MAX_SOURCE_BYTES
            or len(body) != before_fd.st_size
            or _stat_identity(before_fd) != _stat_identity(after_fd)
            or _stat_identity(before_fd) != _stat_identity(after_path)
        ):
            raise UserCsvAuditError("DATASET_CSV_SOURCE_CHANGED_DURING_READ")
        return body
    finally:
        os.close(descriptor)


def _parse_csv(body: bytes) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UserCsvAuditError("DATASET_CSV_NOT_UTF8") from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        columns = reader.fieldnames
        if not columns or any(not isinstance(name, str) or not name.strip() for name in columns):
            raise UserCsvAuditError("DATASET_CSV_HEADER_INVALID")
        if len(set(columns)) != len(columns):
            raise UserCsvAuditError("DATASET_CSV_DUPLICATE_HEADER")
        missing = sorted(set(REQUIRED_COLUMNS) - set(columns))
        if missing:
            raise UserCsvAuditError("DATASET_CSV_REQUIRED_COLUMNS_MISSING:" + ",".join(missing))
        records: list[dict[str, str | None]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise UserCsvAuditError(f"DATASET_CSV_ROW_WIDTH_INVALID:{row_number}")
            records.append(row)
            if len(records) > MAX_ROWS:
                raise UserCsvAuditError("DATASET_CSV_ROW_LIMIT_EXCEEDED")
        return list(columns), records
    except csv.Error as exc:
        raise UserCsvAuditError("DATASET_CSV_PARSE_FAILED") from exc


def _audit_records(records: list[dict[str, str | None]], dataset_id: str) -> DatasetAuditReport:
    audit = audit_ohlcv(records)
    missing_required = sum(
        1
        for row in records
        for column in REQUIRED_COLUMNS
        if row.get(column) is None or not str(row.get(column)).strip()
    )
    if missing_required or not records:
        findings = set(audit.findings)
        findings.add("REQUIRED_VALUE_MISSING" if missing_required else "NO_DATA_ROWS")
        audit = replace(
            audit,
            quality_status=QualityStatus.CRITICAL,
            findings=tuple(sorted(findings)),
        )
    return replace(audit, dataset_id=dataset_id)


def _decimal_tolerance(value: str | int | float | Decimal, name: str) -> Decimal:
    if isinstance(value, bool) or len(str(value)) > 128:
        raise UserCsvAuditError(f"DATASET_COMPARISON_{name}_INVALID")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise UserCsvAuditError(f"DATASET_COMPARISON_{name}_INVALID") from exc
    if not parsed.is_finite() or parsed < 0:
        raise UserCsvAuditError(f"DATASET_COMPARISON_{name}_INVALID")
    upper_bound = Decimal("1e12") if name == "ABSOLUTE_TOLERANCE" else Decimal("1")
    if parsed > upper_bound:
        raise UserCsvAuditError(f"DATASET_COMPARISON_{name}_INVALID")
    return parsed


def _comparison_number(value: str | None, field: str) -> Decimal:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise UserCsvAuditError(f"DATASET_COMPARISON_NUMERIC_VALUE_INVALID:{field}")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise UserCsvAuditError(f"DATASET_COMPARISON_NUMERIC_VALUE_INVALID:{field}") from exc
    if not parsed.is_finite() or parsed.adjusted() < -324 or parsed.adjusted() > 308:
        raise UserCsvAuditError(f"DATASET_COMPARISON_NUMERIC_RANGE_INVALID:{field}")
    return parsed


def _comparison_key(row: dict[str, str | None]) -> tuple[str, str]:
    try:
        value = str(row.get("event_time", "")).strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        event_time = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise UserCsvAuditError("DATASET_COMPARISON_EVENT_TIME_INVALID") from exc
    if event_time.tzinfo is None or event_time.utcoffset() is None:
        raise UserCsvAuditError("DATASET_COMPARISON_TIMEZONE_REQUIRED")
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol:
        raise UserCsvAuditError("DATASET_COMPARISON_SYMBOL_REQUIRED")
    return event_time.astimezone(UTC).isoformat(timespec="microseconds"), symbol


def _index_comparison_records(
    records: list[dict[str, str | None]],
) -> dict[tuple[str, str], dict[str, str | None]]:
    indexed: dict[tuple[str, str], dict[str, str | None]] = {}
    for row in records:
        key = _comparison_key(row)
        if key in indexed:
            raise UserCsvAuditError("DATASET_COMPARISON_DUPLICATE_UTC_SYMBOL_KEY")
        indexed[key] = row
    return indexed


def _compare_records(
    primary_records: list[dict[str, str | None]],
    comparison_records: list[dict[str, str | None]],
    primary_audit: DatasetAuditReport,
    comparison_audit: DatasetAuditReport,
    *,
    absolute_tolerance: Decimal,
    relative_tolerance: Decimal,
) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "INCOMPARABLE",
        "agreement": "NOT_ASSESSED",
        "primary_row_count": len(primary_records),
        "comparison_row_count": len(comparison_records),
        "matched_key_count": 0,
        "primary_only_key_count": None,
        "comparison_only_key_count": None,
        "divergent_row_count": None,
        "field_difference_counts": {field: None for field in ("open", "high", "low", "close", "volume")},
        "maximum_absolute_difference": None,
        "join_key": ["event_time_normalized_to_utc_microseconds", "symbol_trimmed_uppercase"],
        "compared_fields": ["open", "high", "low", "close", "volume"],
        "tolerance": {
            "absolute": str(absolute_tolerance),
            "relative": str(relative_tolerance),
            "rule": "difference <= absolute + relative * max(abs(primary), abs(comparison))",
        },
        "authoritative": False,
        "source_independence": "NOT_VERIFIED",
        "required_before_use": True,
    }
    reasons: list[str] = []
    if not primary_records or not comparison_records:
        reasons.append("EMPTY_SOURCE")
    if primary_audit.quality_status in {QualityStatus.INVALID, QualityStatus.CRITICAL}:
        reasons.append("PRIMARY_SOURCE_QUALITY_CRITICAL")
    if comparison_audit.quality_status in {QualityStatus.INVALID, QualityStatus.CRITICAL}:
        reasons.append("COMPARISON_SOURCE_QUALITY_CRITICAL")
    if primary_audit.duplicate_count or comparison_audit.duplicate_count:
        reasons.append("DUPLICATE_OBSERVATIONS")
    if not primary_audit.timezone_aware_event_time or not comparison_audit.timezone_aware_event_time:
        reasons.append("TIMEZONE_AWARE_EVENT_TIME_REQUIRED")
    if reasons:
        base["reasons"] = sorted(set(reasons))
        return base

    try:
        primary_index = _index_comparison_records(primary_records)
        comparison_index = _index_comparison_records(comparison_records)
    except UserCsvAuditError as exc:
        base["reasons"] = [str(exc)]
        return base
    primary_keys = set(primary_index)
    comparison_keys = set(comparison_index)
    shared_keys = primary_keys & comparison_keys
    primary_only = len(primary_keys - comparison_keys)
    comparison_only = len(comparison_keys - primary_keys)
    difference_counts = {field: 0 for field in ("open", "high", "low", "close", "volume")}
    divergent_rows = 0
    maximum_difference = Decimal("0")
    try:
        with localcontext() as context:
            context.prec = 1024
            for key in shared_keys:
                primary_row = primary_index[key]
                comparison_row = comparison_index[key]
                row_divergent = False
                for field in difference_counts:
                    primary_value = _comparison_number(primary_row.get(field), field)
                    comparison_value = _comparison_number(comparison_row.get(field), field)
                    difference = abs(primary_value - comparison_value)
                    maximum_difference = max(maximum_difference, difference)
                    allowed_difference = absolute_tolerance + relative_tolerance * max(
                        abs(primary_value), abs(comparison_value)
                    )
                    if difference > allowed_difference:
                        difference_counts[field] += 1
                        row_divergent = True
                if row_divergent:
                    divergent_rows += 1
    except UserCsvAuditError as exc:
        base["reasons"] = [str(exc)]
        return base

    agreement = (
        "MATCH"
        if shared_keys and not primary_only and not comparison_only and not divergent_rows
        else "REVIEW_REQUIRED"
    )
    if not shared_keys:
        agreement = "NO_OVERLAP"
    base.update({
        "status": "COMPLETED",
        "agreement": agreement,
        "matched_key_count": len(shared_keys),
        "primary_only_key_count": primary_only,
        "comparison_only_key_count": comparison_only,
        "divergent_row_count": divergent_rows,
        "field_difference_counts": difference_counts,
        "maximum_absolute_difference": str(maximum_difference),
        "same_source_bytes": None,
    })
    return base


def _aware_event_times(records: list[dict[str, str | None]]) -> list[datetime]:
    result: list[datetime] = []
    for row in records:
        try:
            value = str(row.get("event_time", "")).strip()
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            result.append(parsed)
    return result


def _safe_report_path(report_path: str | Path, source_path: Path) -> Path:
    target = Path(report_path).expanduser()
    resolved = target.resolve()
    repository_root = Path(__file__).resolve().parents[3]
    if resolved == repository_root or resolved.is_relative_to(repository_root):
        raise UserCsvAuditError("DATASET_AUDIT_REPORT_INSIDE_REPOSITORY")
    if resolved == source_path.resolve():
        raise UserCsvAuditError("DATASET_AUDIT_REPORT_EQUALS_SOURCE")
    return target


def _make_dataset_contract(
    *,
    dataset_id: str,
    source_label: str,
    source_path: Path,
    source_hash: str,
    columns: list[str],
    records: list[dict[str, str | None]],
    audit: DatasetAuditReport,
) -> DatasetContract | None:
    times = _aware_event_times(records)
    if not records or not audit.timezone_aware_event_time or len(times) != len(records):
        return None
    contract = DatasetContract(
        dataset_id=dataset_id,
        dataset_version="1",
        schema_version="USER_OHLCV_CSV_V1",
        source=source_label.strip(),
        snapshot_id=f"sha256:{source_hash}",
        lineage=(f"file:{source_path.name}", f"sha256:{source_hash}"),
        content_hash=content_hash(records),
        schema_hash=hashlib.sha256(canonical_json(columns).encode("utf-8")).hexdigest(),
        coverage_start=min(times),
        coverage_end=max(times) + timedelta(milliseconds=1),
        quality_status=audit.quality_status,
        quality_report=canonical_json(audit.to_dict()),
        retention_policy="Original source is not copied; operator retains the source and audit report.",
        ingestion_time=datetime.now(UTC),
    )
    contract.validate()
    return contract


def _contract_payload(contract: DatasetContract | None) -> dict[str, object] | None:
    if contract is None:
        return None
    return {
        **asdict(contract),
        "coverage_start": contract.coverage_start.isoformat(),
        "coverage_end": contract.coverage_end.isoformat(),
        "ingestion_time": contract.ingestion_time.isoformat(),
        "quality_status": contract.quality_status.value,
    }


def _write_report_exclusive(path: Path, payload: dict[str, object]) -> None:
    body = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(body) > MAX_REPORT_BYTES:
        raise UserCsvAuditError("DATASET_AUDIT_REPORT_TOO_LARGE")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        os.close(descriptor)


def audit_user_dataset_csv(
    *,
    input_path: str | Path,
    source_label: str,
    report_path: str | Path,
    dataset_id: str = "DATASET-01",
    anomaly_note: str | None = None,
    comparison_anomaly_note: str | None = None,
    comparison_input_path: str | Path | None = None,
    comparison_source_label: str | None = None,
    absolute_tolerance: str | int | float | Decimal = "0",
    relative_tolerance: str | int | float | Decimal = "0",
) -> UserCsvAuditResult:
    """Audit a user/vendor OHLCV CSV without copying it or using the network.

    The report binds the source bytes and parsed content to a DatasetContract
    when timezone-aware coverage can be established. Optional source comparison
    uses a second local CSV; matching data does not prove source independence,
    licensing, or authority for definitive use.
    """
    if not isinstance(dataset_id, str) or not _DATASET_ID.fullmatch(dataset_id):
        raise UserCsvAuditError("DATASET_ID_INVALID")
    if not isinstance(source_label, str) or not source_label.strip() or len(source_label.strip()) > 200:
        raise UserCsvAuditError("DATASET_SOURCE_LABEL_INVALID")
    if anomaly_note is not None and (not isinstance(anomaly_note, str) or len(anomaly_note) > 2000):
        raise UserCsvAuditError("DATASET_ANOMALY_NOTE_INVALID")
    if comparison_anomaly_note is not None and (
        not isinstance(comparison_anomaly_note, str) or len(comparison_anomaly_note) > 2000
    ):
        raise UserCsvAuditError("DATASET_COMPARISON_ANOMALY_NOTE_INVALID")
    source_path = Path(input_path).expanduser()
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    if (comparison_input_path is None) != (comparison_source_label is None):
        raise UserCsvAuditError("DATASET_COMPARISON_SOURCE_AND_LABEL_REQUIRED_TOGETHER")
    comparison_path: Path | None = None
    if comparison_input_path is not None:
        if (
            not isinstance(comparison_source_label, str)
            or not comparison_source_label.strip()
            or len(comparison_source_label.strip()) > 200
        ):
            raise UserCsvAuditError("DATASET_COMPARISON_SOURCE_LABEL_INVALID")
        if comparison_source_label.strip().casefold() == source_label.strip().casefold():
            raise UserCsvAuditError("DATASET_COMPARISON_SOURCE_LABELS_MUST_DIFFER")
        comparison_path = Path(comparison_input_path).expanduser()
        if not comparison_path.is_absolute():
            comparison_path = Path.cwd() / comparison_path
        if comparison_path.resolve() == source_path.resolve():
            raise UserCsvAuditError("DATASET_COMPARISON_SOURCES_MUST_DIFFER")
    absolute_limit = _decimal_tolerance(absolute_tolerance, "ABSOLUTE_TOLERANCE")
    relative_limit = _decimal_tolerance(relative_tolerance, "RELATIVE_TOLERANCE")
    report = _safe_report_path(report_path, source_path)
    if comparison_path is not None:
        report = _safe_report_path(report, comparison_path)
    body = _read_stable_source(source_path)
    columns, records = _parse_csv(body)
    source_hash = hashlib.sha256(body).hexdigest()
    audit = _audit_records(records, dataset_id)
    comparison_body: bytes | None = None
    comparison_columns: list[str] | None = None
    comparison_records: list[dict[str, str | None]] | None = None
    comparison_audit: DatasetAuditReport | None = None
    comparison_hash: str | None = None
    if comparison_path is not None:
        comparison_body = _read_stable_source(comparison_path)
        comparison_columns, comparison_records = _parse_csv(comparison_body)
        comparison_hash = hashlib.sha256(comparison_body).hexdigest()
        comparison_audit = _audit_records(comparison_records, dataset_id)
    times = _aware_event_times(records)
    temporal_complete = bool(records) and len(times) == len(records)
    contract = _make_dataset_contract(
        dataset_id=dataset_id,
        source_label=source_label,
        source_path=source_path,
        source_hash=source_hash,
        columns=columns,
        records=records,
        audit=audit,
    )
    comparison_contract_id = f"{dataset_id[:56]}-COMPARE"
    comparison_contract = None
    if (
        comparison_path is not None
        and comparison_columns is not None
        and comparison_records is not None
        and comparison_audit is not None
    ):
        comparison_contract = _make_dataset_contract(
            dataset_id=comparison_contract_id,
            source_label=comparison_source_label,
            source_path=comparison_path,
            source_hash=comparison_hash,
            columns=comparison_columns,
            records=comparison_records,
            audit=comparison_audit,
        )

    source_comparison: dict[str, object]
    if comparison_path is None or comparison_records is None or comparison_audit is None:
        source_comparison = {
            "status": "NOT_PERFORMED_SINGLE_SOURCE",
            "authoritative": False,
            "required_before_use": True,
            "source_independence": "NOT_VERIFIED",
        }
        comparison_status = "NOT_PERFORMED_SINGLE_SOURCE"
    else:
        source_comparison = _compare_records(
            records,
            comparison_records,
            audit,
            comparison_audit,
            absolute_tolerance=absolute_limit,
            relative_tolerance=relative_limit,
        )
        source_comparison["sources"] = [
            {
                "dataset_id": dataset_id,
                "label": source_label.strip(),
                "file_name": source_path.name,
                "sha256": source_hash,
                "quality_status": audit.quality_status.value,
            },
            {
                "dataset_id": comparison_contract_id,
                "label": comparison_source_label.strip(),
                "file_name": comparison_path.name,
                "sha256": comparison_hash,
                "quality_status": comparison_audit.quality_status.value,
            },
        ]
        source_comparison["same_source_bytes"] = comparison_hash == source_hash
        source_comparison["comparison_quality_report"] = comparison_audit.to_dict()
        source_comparison["comparison_anomaly_documentation"] = {
            "automated_findings": list(comparison_audit.findings),
            "operator_note": (
                comparison_anomaly_note.strip()
                if comparison_anomaly_note and comparison_anomaly_note.strip()
                else None
            ),
            "status": (
                "DOCUMENTED"
                if comparison_anomaly_note and comparison_anomaly_note.strip()
                else "OPERATOR_REVIEW_REQUIRED"
            ),
        }
        comparison_status = str(source_comparison["agreement"])

    report_payload: dict[str, object] = {
        "schema_version": "DATASET_01_LOCAL_CSV_AUDIT_V2",
        "dataset_contract": _contract_payload(contract),
        "comparison_dataset_contract": _contract_payload(comparison_contract),
        "source_file": {
            "name": source_path.name,
            "size_bytes": len(body),
            "sha256": source_hash,
            "copied": False,
        },
        "source_label": source_label.strip(),
        "source_license_assessment": "NOT_ASSESSED",
        "dataset_authority": (
            "NOT_AUTHORIZED_BY_SINGLE_SOURCE_AUDIT"
            if comparison_path is None
            else "NOT_AUTHORIZED_BY_LOCAL_SOURCE_COMPARISON"
        ),
        "source_comparison": source_comparison,
        "temporal_validation": {
            "timezone_aware": temporal_complete,
            "out_of_order": audit.out_of_order,
            "status": "PASS" if temporal_complete and not audit.out_of_order else "REVIEW_REQUIRED",
        },
        "anomaly_documentation": {
            "automated_findings": list(audit.findings),
            "operator_note": anomaly_note.strip() if anomaly_note and anomaly_note.strip() else None,
            "status": "DOCUMENTED" if anomaly_note and anomaly_note.strip() else "OPERATOR_REVIEW_REQUIRED",
        },
        "quality_report": audit.to_dict(),
        "network_used": False,
        "production_ready": False,
    }
    _write_report_exclusive(report, report_payload)
    comparison_failed = comparison_path is not None and comparison_status != "MATCH"
    quality_review_required = audit.quality_status is not QualityStatus.VALID or (
        comparison_audit is not None and comparison_audit.quality_status is not QualityStatus.VALID
    )
    exit_code = (
        1
        if contract is None
        or quality_review_required
        or comparison_failed
        else 0
    )
    return UserCsvAuditResult(
        report,
        contract,
        audit.quality_status,
        len(records),
        exit_code,
        source_hash,
        comparison_status,
    )

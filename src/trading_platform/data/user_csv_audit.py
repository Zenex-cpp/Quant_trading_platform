"""Bounded, local-only audit of a user/vendor OHLCV CSV for DATASET-01."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
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
) -> UserCsvAuditResult:
    """Audit a user/vendor OHLCV CSV without copying it or using the network.

    The report binds the source bytes and parsed content to a DatasetContract
    when timezone-aware coverage can be established. A single-source report is
    never authoritative, and the source license is intentionally not inferred.
    """
    if not isinstance(dataset_id, str) or not _DATASET_ID.fullmatch(dataset_id):
        raise UserCsvAuditError("DATASET_ID_INVALID")
    if not isinstance(source_label, str) or not source_label.strip() or len(source_label.strip()) > 200:
        raise UserCsvAuditError("DATASET_SOURCE_LABEL_INVALID")
    if anomaly_note is not None and (not isinstance(anomaly_note, str) or len(anomaly_note) > 2000):
        raise UserCsvAuditError("DATASET_ANOMALY_NOTE_INVALID")
    source_path = Path(input_path).expanduser()
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    report = _safe_report_path(report_path, source_path)
    body = _read_stable_source(source_path)
    columns, records = _parse_csv(body)
    source_hash = hashlib.sha256(body).hexdigest()
    audit: DatasetAuditReport = audit_ohlcv(records)
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
    audit = replace(audit, dataset_id=dataset_id)
    times = _aware_event_times(records)
    temporal_complete = bool(records) and len(times) == len(records)
    contract: DatasetContract | None = None
    if records and audit.timezone_aware_event_time and len(times) == len(records):
        coverage_start = min(times)
        coverage_end = max(times) + timedelta(milliseconds=1)
        canonical_content_hash = content_hash(records)
        schema_hash = hashlib.sha256(canonical_json(columns).encode("utf-8")).hexdigest()
        contract = DatasetContract(
            dataset_id=dataset_id,
            dataset_version="1",
            schema_version="USER_OHLCV_CSV_V1",
            source=source_label.strip(),
            snapshot_id=f"sha256:{source_hash}",
            lineage=(f"file:{source_path.name}", f"sha256:{source_hash}"),
            content_hash=canonical_content_hash,
            schema_hash=schema_hash,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            quality_status=audit.quality_status,
            quality_report=canonical_json(audit.to_dict()),
            retention_policy="Original source is not copied; operator retains the source and audit report.",
            ingestion_time=datetime.now(UTC),
        )
        contract.validate()

    report_payload: dict[str, object] = {
        "schema_version": "DATASET_01_LOCAL_CSV_AUDIT_V1",
        "dataset_contract": None if contract is None else {
            **asdict(contract),
            "coverage_start": contract.coverage_start.isoformat(),
            "coverage_end": contract.coverage_end.isoformat(),
            "ingestion_time": contract.ingestion_time.isoformat(),
            "quality_status": contract.quality_status.value,
        },
        "source_file": {
            "name": source_path.name,
            "size_bytes": len(body),
            "sha256": source_hash,
            "copied": False,
        },
        "source_label": source_label.strip(),
        "source_license_assessment": "NOT_ASSESSED",
        "dataset_authority": "NOT_AUTHORIZED_BY_SINGLE_SOURCE_AUDIT",
        "source_comparison": {
            "status": "NOT_PERFORMED_SINGLE_SOURCE",
            "authoritative": False,
            "required_before_use": True,
        },
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
    exit_code = 1 if contract is None or audit.quality_status in {QualityStatus.INVALID, QualityStatus.CRITICAL} else 0
    return UserCsvAuditResult(report, contract, audit.quality_status, len(records), exit_code, source_hash)

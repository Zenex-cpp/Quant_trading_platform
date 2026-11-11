"""Bounded, read-only ingestion of Binance USD-M Futures daily kline archives.

This adapter consumes the public archive only. It has no API-key support and
never calls an exchange trading or account endpoint.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import tempfile
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

from trading_platform.data.dataset import DatasetAuditReport, audit_ohlcv
from trading_platform.data_v03 import DatasetContract, QualityStatus, canonical_json, content_hash
from trading_platform.v391.network_segmentation import (
    NetworkSegmentationPolicyV391,
    NetworkZoneV391,
)

UTC = timezone.utc
PUBLIC_DATA_BASE = "https://data.binance.vision"
PUBLIC_DATA_HOST = "data.binance.vision"
PUBLIC_DATA_TERMS_URL = "https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md"
PUBLIC_DATA_LICENSE = "CC BY-NC-SA 4.0; non-commercial research scope only"
KLINE_INTERVALS = frozenset({
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d",
})
CSV_COLUMNS = (
    "event_time", "symbol", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
)
SOURCE_COLUMNS = (
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume", "ignore",
)
MAX_DAYS = 31
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TOTAL_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ROWS = 50_000
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class PublicDataImportError(ValueError):
    """Raised when a public archive or its normalized data fails validation."""


@dataclass(frozen=True)
class ArchiveRecord:
    date: str
    url: str
    checksum_url: str
    sha256: str
    row_count: int


@dataclass(frozen=True)
class ImportResult:
    output_path: Path
    manifest_path: Path
    dataset_contract: DatasetContract
    row_count: int
    content_hash: str


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PublicDataImportError("PUBLIC_DATA_REDIRECT_REJECTED")


def _https_get(url: str, limit: int) -> bytes:
    """GET a bounded body with proxies and redirects disabled."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != PUBLIC_DATA_HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PublicDataImportError("PUBLIC_DATA_URL_OUTSIDE_ALLOWLIST")
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    request = Request(url, method="GET", headers={"User-Agent": "trading-platform-public-data/3.61.13"})
    try:
        with opener.open(request, timeout=20) as response:
            if response.geturl() != url:
                raise PublicDataImportError("PUBLIC_DATA_RESPONSE_URL_CHANGED")
            body = response.read(limit + 1)
    except HTTPError as exc:
        raise PublicDataImportError(f"PUBLIC_DATA_HTTP_STATUS:{exc.code}") from exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise PublicDataImportError(f"PUBLIC_DATA_TRANSPORT_FAILED:{type(exc).__name__}") from exc
    if len(body) > limit:
        raise PublicDataImportError("PUBLIC_DATA_RESPONSE_TOO_LARGE")
    return body


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_names(symbol: str, interval: str, day: date) -> tuple[str, str]:
    stem = f"{symbol}-{interval}-{day.isoformat()}"
    return f"{stem}.zip", f"{stem}.csv"


def _archive_url(symbol: str, interval: str, day: date, *, checksum: bool = False) -> str:
    archive, _ = _archive_names(symbol, interval, day)
    name = f"{archive}.CHECKSUM" if checksum else archive
    return (
        f"{PUBLIC_DATA_BASE}/data/futures/um/daily/klines/"
        f"{symbol}/{interval}/{name}"
    )


def _parse_checksum(body: bytes, archive_name: str) -> str:
    if len(body) > MAX_CHECKSUM_BYTES:
        raise PublicDataImportError("PUBLIC_DATA_CHECKSUM_TOO_LARGE")
    try:
        text = body.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise PublicDataImportError("PUBLIC_DATA_CHECKSUM_NOT_ASCII") from exc
    parts = text.split()
    if len(parts) != 2 or not _SHA256.fullmatch(parts[0]):
        raise PublicDataImportError("PUBLIC_DATA_CHECKSUM_FORMAT_INVALID")
    filename = parts[1].removeprefix("*")
    if filename != archive_name:
        raise PublicDataImportError("PUBLIC_DATA_CHECKSUM_FILENAME_MISMATCH")
    return parts[0].lower()


def _safe_archive_csv(body: bytes, expected_member: str) -> bytes:
    try:
        with ZipFile(io.BytesIO(body)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise PublicDataImportError("PUBLIC_DATA_ARCHIVE_MEMBER_COUNT_INVALID")
            info = members[0]
            member_path = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            if (
                member_path.name != expected_member
                or member_path.is_absolute()
                or len(member_path.parts) != 1
                or "\\" in info.filename
                or "\x00" in info.filename
                or info.is_dir()
                or stat.S_ISLNK(mode)
                or info.flag_bits & 0x1
            ):
                raise PublicDataImportError("PUBLIC_DATA_ARCHIVE_MEMBER_UNSAFE")
            if info.file_size < 1 or info.file_size > MAX_UNCOMPRESSED_BYTES:
                raise PublicDataImportError("PUBLIC_DATA_UNCOMPRESSED_SIZE_INVALID")
            with archive.open(info, "r") as stream:
                content = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
            if len(content) != info.file_size or len(content) > MAX_UNCOMPRESSED_BYTES:
                raise PublicDataImportError("PUBLIC_DATA_UNCOMPRESSED_SIZE_MISMATCH")
            return content
    except BadZipFile as exc:
        raise PublicDataImportError("PUBLIC_DATA_ZIP_INVALID") from exc


def _decimal(value: str, column: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise PublicDataImportError(f"PUBLIC_DATA_NUMERIC_INVALID:{column}") from exc
    if not result.is_finite():
        raise PublicDataImportError(f"PUBLIC_DATA_NUMERIC_NONFINITE:{column}")
    return result


def _interval_millis(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    try:
        return int(interval[:-1]) * units[interval[-1]]
    except (KeyError, ValueError) as exc:
        raise PublicDataImportError("PUBLIC_DATA_INTERVAL_UNSUPPORTED") from exc


def _parse_day_csv(content: bytes, *, symbol: str, interval: str, day: date) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublicDataImportError("PUBLIC_DATA_CSV_NOT_UTF8") from exc
    rows: list[dict[str, str]] = []
    previous_open_ms: int | None = None
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    for line_number, fields in enumerate(reader, start=1):
        if not fields or all(not field.strip() for field in fields):
            continue
        if len(fields) != len(SOURCE_COLUMNS):
            raise PublicDataImportError(f"PUBLIC_DATA_COLUMN_COUNT_INVALID:{line_number}")
        try:
            open_ms = int(fields[0])
            close_ms = int(fields[6])
        except ValueError as exc:
            raise PublicDataImportError(f"PUBLIC_DATA_TIMESTAMP_INVALID:{line_number}") from exc
        if open_ms < 0 or close_ms < open_ms:
            raise PublicDataImportError(f"PUBLIC_DATA_TIMESTAMP_RANGE_INVALID:{line_number}")
        if previous_open_ms is not None and open_ms <= previous_open_ms:
            raise PublicDataImportError(f"PUBLIC_DATA_KLINE_ORDER_OR_DUPLICATE_INVALID:{line_number}")
        previous_open_ms = open_ms
        event_time = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=open_ms)
        if event_time.date() != day:
            raise PublicDataImportError(f"PUBLIC_DATA_ROW_OUTSIDE_ARCHIVE_DAY:{line_number}")
        if open_ms % _interval_millis(interval) != 0:
            raise PublicDataImportError(f"PUBLIC_DATA_INTERVAL_ALIGNMENT_INVALID:{line_number}")
        if close_ms != open_ms + _interval_millis(interval) - 1:
            raise PublicDataImportError(f"PUBLIC_DATA_CLOSE_TIME_INVALID:{line_number}")
        for idx in (1, 2, 3, 4, 5, 7, 9, 10, 11):
            _decimal(fields[idx], SOURCE_COLUMNS[idx])
        try:
            trade_count = int(fields[8])
        except ValueError as exc:
            raise PublicDataImportError(f"PUBLIC_DATA_TRADE_COUNT_INVALID:{line_number}") from exc
        if trade_count < 0:
            raise PublicDataImportError(f"PUBLIC_DATA_TRADE_COUNT_INVALID:{line_number}")
        rows.append({
            "event_time": event_time.isoformat().replace("+00:00", "Z"),
            "symbol": symbol,
            "open": fields[1],
            "high": fields[2],
            "low": fields[3],
            "close": fields[4],
            "volume": fields[5],
            "close_time": (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=close_ms)).isoformat().replace("+00:00", "Z"),
            "quote_asset_volume": fields[7],
            "number_of_trades": str(trade_count),
            "taker_buy_base_asset_volume": fields[9],
            "taker_buy_quote_asset_volume": fields[10],
            "ignore": fields[11],
        })
        if len(rows) > MAX_ROWS:
            raise PublicDataImportError("PUBLIC_DATA_ROW_LIMIT_EXCEEDED")
    return rows


def _validate_request(symbol: str, interval: str, start_date: date, end_date: date) -> list[date]:
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise PublicDataImportError("PUBLIC_DATA_SYMBOL_INVALID")
    if not isinstance(interval, str) or interval not in KLINE_INTERVALS:
        raise PublicDataImportError("PUBLIC_DATA_INTERVAL_UNSUPPORTED")
    if type(start_date) is not date or type(end_date) is not date:
        raise PublicDataImportError("PUBLIC_DATA_DATE_INVALID")
    if start_date > end_date:
        raise PublicDataImportError("PUBLIC_DATA_DATE_RANGE_INVALID")
    days = (end_date - start_date).days + 1
    if days > MAX_DAYS:
        raise PublicDataImportError(f"PUBLIC_DATA_RANGE_LIMIT_EXCEEDED:{MAX_DAYS}")
    return [start_date + timedelta(days=offset) for offset in range(days)]


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def import_um_daily_klines(
    *,
    symbol: str,
    interval: str,
    start_date: date,
    end_date: date,
    output_dir: str | Path,
    confirm_noncommercial_research: bool = False,
    transport: Callable[[str, int], bytes] | None = None,
    network_policy: NetworkSegmentationPolicyV391 | None = None,
) -> ImportResult:
    """Import daily USD-M Futures kline archives for inclusive UTC dates.

    A new content-addressed snapshot directory is created atomically. Existing
    snapshots are never replaced. ``transport`` is injectable for tests; the
    default transport is HTTPS GET with proxies and redirects disabled. Binance
    Vision terms restrict this source to non-commercial research and exclude
    live proprietary/commercial trading use; callers must explicitly attest.
    """
    if confirm_noncommercial_research is not True:
        raise PublicDataImportError("PUBLIC_DATA_TERMS_CONFIRMATION_REQUIRED")
    days = _validate_request(symbol, interval, start_date, end_date)
    fetch = transport or _https_get
    policy = network_policy or NetworkSegmentationPolicyV391()
    parent = Path(output_dir).expanduser()
    resolved_parent = parent.resolve()
    repository_root = Path(__file__).resolve().parents[3]
    if resolved_parent == repository_root or resolved_parent.is_relative_to(repository_root):
        raise PublicDataImportError("PUBLIC_DATA_OUTPUT_INSIDE_REPOSITORY")
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir():
        raise PublicDataImportError("PUBLIC_DATA_OUTPUT_NOT_DIRECTORY")
    stage = Path(tempfile.mkdtemp(prefix=".public-data-stage-", dir=parent))
    records: list[dict[str, str]] = []
    archives: list[ArchiveRecord] = []
    coverage: list[dict[str, int | str]] = []
    total_archive_bytes = 0
    total_uncompressed_bytes = 0
    try:
        raw_dir = stage / "raw"
        raw_dir.mkdir()
        for day in days:
            archive_name, member_name = _archive_names(symbol, interval, day)
            url = _archive_url(symbol, interval, day)
            checksum_url = _archive_url(symbol, interval, day, checksum=True)
            policy.assert_allowed(NetworkZoneV391.PUBLIC_MARKET_DATA, url)
            policy.assert_allowed(NetworkZoneV391.PUBLIC_MARKET_DATA, checksum_url)
            checksum_body = fetch(checksum_url, MAX_CHECKSUM_BYTES)
            expected_hash = _parse_checksum(checksum_body, archive_name)
            archive_body = fetch(url, MAX_ARCHIVE_BYTES)
            if len(archive_body) > MAX_ARCHIVE_BYTES:
                raise PublicDataImportError("PUBLIC_DATA_ARCHIVE_TOO_LARGE")
            archive_hash = _sha256(archive_body)
            if archive_hash != expected_hash:
                raise PublicDataImportError(f"PUBLIC_DATA_CHECKSUM_MISMATCH:{day.isoformat()}")
            csv_body = _safe_archive_csv(archive_body, member_name)
            total_archive_bytes += len(archive_body)
            total_uncompressed_bytes += len(csv_body)
            if total_archive_bytes > MAX_TOTAL_ARCHIVE_BYTES:
                raise PublicDataImportError("PUBLIC_DATA_TOTAL_ARCHIVE_LIMIT_EXCEEDED")
            if total_uncompressed_bytes > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise PublicDataImportError("PUBLIC_DATA_TOTAL_UNCOMPRESSED_LIMIT_EXCEEDED")
            try:
                day_records = _parse_day_csv(csv_body, symbol=symbol, interval=interval, day=day)
            except csv.Error as exc:
                raise PublicDataImportError("PUBLIC_DATA_CSV_PARSE_FAILED") from exc
            records.extend(day_records)
            if len(records) > MAX_ROWS:
                raise PublicDataImportError("PUBLIC_DATA_ROW_LIMIT_EXCEEDED")
            expected_rows = 86_400_000 // _interval_millis(interval)
            coverage.append({
                "date": day.isoformat(),
                "expected_rows": expected_rows,
                "observed_rows": len(day_records),
                "missing_rows": max(0, expected_rows - len(day_records)),
            })
            _write_exclusive(raw_dir / archive_name, archive_body)
            _write_exclusive(raw_dir / f"{archive_name}.CHECKSUM", checksum_body)
            archives.append(ArchiveRecord(day.isoformat(), url, checksum_url, archive_hash, len(day_records)))

        if not records:
            raise PublicDataImportError("PUBLIC_DATA_NO_ROWS_IN_REQUESTED_RANGE")
        quality: DatasetAuditReport = audit_ohlcv(records)
        if quality.duplicate_count or quality.quality_status in {QualityStatus.CRITICAL, QualityStatus.INVALID}:
            raise PublicDataImportError("PUBLIC_DATA_QUALITY_AUDIT_FAILED:" + ",".join(quality.findings))
        quality_payload = quality.to_dict()
        missing_rows = sum(int(item["missing_rows"]) for item in coverage)
        if missing_rows:
            quality_payload["quality_status"] = QualityStatus.WARNING.value
            quality_payload["findings"] = sorted(set(quality_payload["findings"]) | {"MISSING_EXPECTED_KLINES"})
        quality_payload["market_coverage_by_utc_day"] = coverage
        data_hash = content_hash(records)
        schema_hash = hashlib.sha256("\n".join(CSV_COLUMNS).encode("utf-8")).hexdigest()
        ingestion_time = datetime.fromtimestamp(time.time(), tz=UTC)
        coverage_start = datetime.fromisoformat(records[0]["event_time"].replace("Z", "+00:00"))
        last_close_time = datetime.fromisoformat(records[-1]["close_time"].replace("Z", "+00:00"))
        coverage_end = last_close_time + timedelta(milliseconds=1)
        dataset_id = f"binance-um-{symbol}-{interval}-{start_date.isoformat()}-{end_date.isoformat()}"
        snapshot_id = f"sha256:{data_hash}"
        contract = DatasetContract(
            dataset_id=dataset_id,
            dataset_version="1",
            schema_version="binance-um-kline-v1",
            source="Binance Public Data USD-M Futures daily kline archive",
            snapshot_id=snapshot_id,
            lineage=tuple(
                item
                for archive in archives
                for item in (archive.url, f"sha256:{archive.sha256}")
            ),
            content_hash=data_hash,
            schema_hash=schema_hash,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            quality_status=QualityStatus(quality_payload["quality_status"]),
            quality_report=canonical_json(quality_payload),
            retention_policy="Immutable raw archives, checksum sidecars, normalized CSV and manifest; operator-managed retention",
            ingestion_time=ingestion_time,
        )
        contract.validate()
        normalized = io.StringIO(newline="")
        writer = csv.DictWriter(normalized, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        _write_exclusive(stage / "klines.csv", normalized.getvalue().encode("utf-8"))
        manifest = {
            "schema_version": "BINANCE_PUBLIC_DATA_IMPORT_MANIFEST_1",
            "dataset_contract": {
                **asdict(contract),
                "coverage_start": contract.coverage_start.isoformat(),
                "coverage_end": contract.coverage_end.isoformat(),
                "ingestion_time": contract.ingestion_time.isoformat(),
                "quality_status": contract.quality_status.value,
            },
            "request": {
                "market": "USD-M Futures",
                "symbol": symbol,
                "interval": interval,
                "start_date_inclusive_utc": start_date.isoformat(),
                "end_date_inclusive_utc": end_date.isoformat(),
                "archive_period": "daily",
                "read_only": True,
                "use_scope": "non-commercial historical research only",
                "license": PUBLIC_DATA_LICENSE,
                "terms_reviewed_at": "2026-11-11",
                "source_terms_url": PUBLIC_DATA_TERMS_URL,
            },
            "archives": [asdict(archive) for archive in archives],
            "normalized_file": {"path": "klines.csv", "sha256": _sha256(normalized.getvalue().encode("utf-8"))},
            "quality_audit": quality_payload,
            "limitations": [
                "Checksum sidecars come from the same public host as the archives and are not an independent authenticity anchor.",
                "Public historical source data is not, by itself, the project's proprietary research dataset or evidence of trading edge.",
                "The source terms exclude live proprietary/commercial trading use and paid signal distribution.",
                "Daily archive availability may lag or contain source corrections; missing or inconsistent archives fail the import.",
            ],
        }
        _write_exclusive(stage / "manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        final_name = f"{dataset_id}-{data_hash[:16]}"
        final_path = parent / final_name
        reservation = parent / f".{final_name}.reserve"
        try:
            reservation_fd = os.open(reservation, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise PublicDataImportError("PUBLIC_DATA_SNAPSHOT_RESERVATION_EXISTS") from exc
        try:
            if os.path.lexists(final_path):
                raise PublicDataImportError("PUBLIC_DATA_SNAPSHOT_ALREADY_EXISTS")
            try:
                stage.rename(final_path)
            except FileExistsError as exc:
                raise PublicDataImportError("PUBLIC_DATA_SNAPSHOT_ALREADY_EXISTS") from exc
        finally:
            os.close(reservation_fd)
            reservation.unlink(missing_ok=True)
        return ImportResult(final_path, final_path / "manifest.json", contract, len(records), data_hash)
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)

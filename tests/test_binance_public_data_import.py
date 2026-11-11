from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

import pytest

from trading_platform.data import binance_public_data as public_data
from trading_platform.data.binance_public_data import (
    PublicDataImportError,
    import_um_daily_klines,
)

UTC = timezone.utc
DAY = date(2026, 11, 10)
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
ARCHIVE_NAME = "BTCUSDT-1h-2026-11-10.zip"


def _rows(*, count: int = 2) -> list[list[str]]:
    day_start = datetime(2026, 11, 10, tzinfo=UTC)
    rows = []
    for hour in range(count):
        opened = int((day_start.timestamp() + hour * 3600) * 1000)
        closed = opened + 3_600_000 - 1
        rows.append([
            str(opened), "100", "110", "90", "105", "1", str(closed),
            "105", "20", "0.5", "52.5", "0",
        ])
    return rows


def _archive(*, member: str | None = None, rows: list[list[str]] | None = None) -> bytes:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member or "BTCUSDT-1h-2026-11-10.csv", "".join(",".join(row) + "\n" for row in (rows or _rows())))
    return body.getvalue()


class _Transport:
    def __init__(self, archive: bytes, *, checksum_name: str = ARCHIVE_NAME, digest: str | None = None):
        self.archive = archive
        self.digest = digest or sha256(archive).hexdigest()
        self.checksum = f"{self.digest}  {checksum_name}\n".encode("ascii")
        self.calls: list[tuple[str, int]] = []

    def __call__(self, url: str, limit: int) -> bytes:
        self.calls.append((url, limit))
        if url.endswith(".zip.CHECKSUM"):
            return self.checksum
        if url.endswith(".zip"):
            return self.archive
        raise AssertionError(f"UNEXPECTED_URL:{url}")


def _import(output: Path, transport: _Transport, **kwargs):
    return import_um_daily_klines(
        symbol=SYMBOL,
        interval=INTERVAL,
        start_date=DAY,
        end_date=DAY,
        output_dir=output,
        confirm_noncommercial_research=True,
        transport=transport,
        **kwargs,
    )


def test_import_writes_immutable_audited_snapshot_and_preserves_raw_archive(tmp_path):
    archive = _archive()
    transport = _Transport(archive)

    result = _import(tmp_path, transport)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    with (result.output_path / "klines.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert result.row_count == 2
    assert [item[0] for item in transport.calls] == [
        "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-11-10.zip.CHECKSUM",
        "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-11-10.zip",
    ]
    assert result.dataset_contract.quality_status.value == "WARNING"
    assert manifest["quality_audit"]["findings"] == ["MISSING_EXPECTED_KLINES"]
    assert manifest["quality_audit"]["market_coverage_by_utc_day"][0]["missing_rows"] == 22
    assert manifest["request"]["use_scope"] == "non-commercial historical research only"
    assert manifest["request"]["source_terms_url"] == public_data.PUBLIC_DATA_TERMS_URL
    assert rows[0]["event_time"] == "2026-11-10T00:00:00Z"
    assert rows[0]["symbol"] == SYMBOL
    assert (result.output_path / "raw" / ARCHIVE_NAME).read_bytes() == archive
    assert (result.output_path / "raw" / f"{ARCHIVE_NAME}.CHECKSUM").is_file()
    with pytest.raises(PublicDataImportError, match="SNAPSHOT_ALREADY_EXISTS"):
        _import(tmp_path, _Transport(archive))


def test_import_requires_noncommercial_research_attestation_before_network_or_files(tmp_path):
    def never_fetch(*args):
        raise AssertionError("NETWORK_MUST_NOT_BE_CALLED")

    with pytest.raises(PublicDataImportError, match="TERMS_CONFIRMATION_REQUIRED"):
        import_um_daily_klines(
            symbol=SYMBOL,
            interval=INTERVAL,
            start_date=DAY,
            end_date=DAY,
            output_dir=tmp_path,
            transport=never_fetch,
        )
    assert list(tmp_path.iterdir()) == []


def test_import_refuses_to_write_license_restricted_data_inside_repository():
    module_path = Path(public_data.__file__)
    repository = module_path.resolve().parents[3]
    inside = repository / "data" / "public-research-test"
    transport = _Transport(_archive())
    with pytest.raises(PublicDataImportError, match="OUTPUT_INSIDE_REPOSITORY"):
        import_um_daily_klines(
            symbol=SYMBOL,
            interval=INTERVAL,
            start_date=DAY,
            end_date=DAY,
            output_dir=inside,
            confirm_noncommercial_research=True,
            transport=transport,
        )
    assert transport.calls == []
    assert not inside.exists()


def test_import_rejects_checksum_mismatch_and_removes_partial_snapshot(tmp_path):
    archive = _archive()
    transport = _Transport(archive, digest="0" * 64)

    with pytest.raises(PublicDataImportError, match="CHECKSUM_MISMATCH"):
        _import(tmp_path, transport)
    assert list(tmp_path.iterdir()) == []


def test_import_rejects_unsafe_zip_member_after_valid_checksum(tmp_path):
    archive = _archive(member="../BTCUSDT-1h-2026-11-10.csv")

    with pytest.raises(PublicDataImportError, match="ARCHIVE_MEMBER_UNSAFE"):
        _import(tmp_path, _Transport(archive))
    assert list(tmp_path.iterdir()) == []


def test_import_rejects_malformed_kline_rows(tmp_path):
    archive = _archive(rows=[["1", "2", "3"]])

    with pytest.raises(PublicDataImportError, match="COLUMN_COUNT_INVALID"):
        _import(tmp_path, _Transport(archive))
    assert list(tmp_path.iterdir()) == []


def test_request_validation_caps_range_and_rejects_invalid_symbol_or_interval(tmp_path):
    transport = _Transport(_archive())
    with pytest.raises(PublicDataImportError, match="RANGE_LIMIT_EXCEEDED"):
        import_um_daily_klines(
            symbol=SYMBOL,
            interval=INTERVAL,
            start_date=DAY,
            end_date=date(2026, 12, 11),
            output_dir=tmp_path,
            confirm_noncommercial_research=True,
            transport=transport,
        )
    with pytest.raises(PublicDataImportError, match="SYMBOL_INVALID"):
        import_um_daily_klines(
            symbol="BTCUSDT/../../x",
            interval=INTERVAL,
            start_date=DAY,
            end_date=DAY,
            output_dir=tmp_path,
            confirm_noncommercial_research=True,
            transport=transport,
        )
    with pytest.raises(PublicDataImportError, match="INTERVAL_UNSUPPORTED"):
        import_um_daily_klines(
            symbol=SYMBOL,
            interval="1mo",
            start_date=DAY,
            end_date=DAY,
            output_dir=tmp_path,
            confirm_noncommercial_research=True,
            transport=transport,
        )
    assert transport.calls == []


def test_transport_rejects_unlisted_host_before_opening_connection(monkeypatch):
    def unexpected_opener(*args, **kwargs):
        raise AssertionError("UNLISTED_URL_MUST_NOT_OPEN")

    monkeypatch.setattr(public_data, "build_opener", unexpected_opener)
    with pytest.raises(PublicDataImportError, match="URL_OUTSIDE_ALLOWLIST"):
        public_data._https_get("https://fapi.binance.com/fapi/v1/klines", 100)


def test_transport_disables_proxies_and_redirects_and_uses_get(monkeypatch):
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def geturl(self):
            return "https://data.binance.vision/archive.zip"

        def read(self, limit):
            return b"zip"

    class _Opener:
        def open(self, request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response()

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return _Opener()

    monkeypatch.setattr(public_data, "build_opener", fake_build_opener)
    assert public_data._https_get("https://data.binance.vision/archive.zip", 10) == b"zip"
    request = captured["request"]
    assert request.get_method() == "GET"
    assert captured["timeout"] == 20
    assert any(isinstance(handler, public_data.ProxyHandler) and handler.proxies == {} for handler in captured["handlers"])
    assert any(isinstance(handler, public_data._RejectRedirects) for handler in captured["handlers"])


def test_cli_requires_terms_acknowledgement_and_passes_through_download_result(monkeypatch, tmp_path, capsys):
    from trading_platform.cli import main

    with pytest.raises(SystemExit):
        main([
            "market-data", "download-um-klines", "--symbol", SYMBOL,
            "--interval", INTERVAL, "--start-date", DAY.isoformat(),
            "--end-date", DAY.isoformat(), "--output", str(tmp_path),
        ])

    fake = _import(tmp_path, _Transport(_archive()))
    monkeypatch.setattr(public_data, "import_um_daily_klines", lambda **kwargs: fake)
    code = main([
        "market-data", "download-um-klines", "--symbol", SYMBOL,
        "--interval", INTERVAL, "--start-date", DAY.isoformat(),
        "--end-date", DAY.isoformat(), "--output", str(tmp_path),
        "--confirm-noncommercial-research",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "IMPORTED"
    assert payload["production_ready"] is False
    assert payload["proprietary_research_dataset"] is False

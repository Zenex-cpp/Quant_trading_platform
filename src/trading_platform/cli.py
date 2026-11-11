"""Command-line entry points for safe, reproducible platform workflows."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Sequence

from trading_platform.v358.e2e_acceptance import run_acceptance


def _offline_acceptance() -> int:
    result = run_acceptance()
    payload = result.payload()
    payload["report_hash"] = result.report_hash
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0 if result.acceptance.acceptance_passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-platform",
        description="Run explicitly scoped, safety-gated platform workflows.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "offline-acceptance",
        help="run the deterministic §178 research-to-audit acceptance flow without network access",
        description=(
            "Execute the complete §178 acceptance chain against synthetic historical data "
            "and local SQLite stores. This command never connects to an exchange."
        ),
    )
    market_data = commands.add_parser(
        "market-data",
        help="acquire public historical market data into an immutable dataset snapshot",
    )
    market_commands = market_data.add_subparsers(dest="market_data_command", required=True)
    download = market_commands.add_parser(
        "download-um-klines",
        help="download checksummed Binance USD-M Futures daily kline archives",
        description=(
            "Read-only public archive download. Uses HTTPS GET on data.binance.vision, "
            "checks each .CHECKSUM, and writes a new immutable snapshot. Non-commercial historical research only. "
            "Inclusive UTC date range; max 31 days."
        ),
    )
    download.add_argument("--symbol", required=True, help="market symbol, for example BTCUSDT")
    download.add_argument("--interval", required=True, help="kline interval, for example 1h")
    download.add_argument("--start-date", required=True, help="inclusive UTC date in YYYY-MM-DD format")
    download.add_argument("--end-date", required=True, help="inclusive UTC date in YYYY-MM-DD format")
    download.add_argument("--output", required=True, help="parent directory for immutable dataset snapshots")
    download.add_argument(
        "--confirm-noncommercial-research",
        action="store_true",
        required=True,
        help="attest the source terms permit non-commercial historical research only (not live/commercial trading)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "offline-acceptance":
        return _offline_acceptance()
    if args.command == "market-data" and args.market_data_command == "download-um-klines":
        from trading_platform.data.binance_public_data import (
            PublicDataImportError,
            import_um_daily_klines,
        )

        try:
            start_date = date.fromisoformat(args.start_date)
            end_date = date.fromisoformat(args.end_date)
            result = import_um_daily_klines(
                symbol=args.symbol.upper(),
                interval=args.interval,
                start_date=start_date,
                end_date=end_date,
                output_dir=args.output,
                confirm_noncommercial_research=args.confirm_noncommercial_research,
            )
        except (PublicDataImportError, OSError, ValueError) as exc:
            print(f"MARKET_DATA_IMPORT=FAILED {type(exc).__name__}:{exc}", file=sys.stderr)
            return 2
        payload = {
            "status": "IMPORTED",
            "dataset_id": result.dataset_contract.dataset_id,
            "dataset_version": result.dataset_contract.dataset_version,
            "snapshot_id": result.dataset_contract.snapshot_id,
            "content_hash": result.content_hash,
            "row_count": result.row_count,
            "quality_status": result.dataset_contract.quality_status.value,
            "output_path": str(result.output_path),
            "manifest_path": str(result.manifest_path),
            "read_only_public_archive": True,
            "production_ready": False,
            "proprietary_research_dataset": False,
            "use_scope": "non-commercial historical research only",
        }
        print(json.dumps(payload, sort_keys=True, indent=2))
        return 0
    raise AssertionError("UNREACHABLE_COMMAND")

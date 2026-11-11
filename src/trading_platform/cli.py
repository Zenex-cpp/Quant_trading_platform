"""Command-line entry points for safe, reproducible platform workflows."""
from __future__ import annotations

import argparse
import json
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "offline-acceptance":
        return _offline_acceptance()
    raise AssertionError("UNREACHABLE_COMMAND")

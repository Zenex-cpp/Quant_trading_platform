#!/usr/bin/env python3
"""Run the deterministic §178 acceptance flow from a source checkout."""
from __future__ import annotations

from pathlib import Path
import sys

# This source-checkout entrypoint must not leave bytecode in the repository;
# the mandatory release-hygiene check rejects generated cache directories.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from trading_platform.cli import main as cli_main


def main() -> int:
    return cli_main(["offline-acceptance"])


if __name__ == "__main__":
    raise SystemExit(main())

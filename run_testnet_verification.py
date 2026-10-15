#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from trading_platform.testnet.runner import RunnerConfig, offline_runner_contract_summary


def main() -> int:
    cfg = RunnerConfig.from_env()
    try:
        cfg.validate()
    except ValueError as exc:
        print(f"CONFIG_ERROR: {exc}")
        return 2
    missing = [k for k in ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET") if not os.environ.get(k)]
    if missing:
        print("MISSING_RUNTIME_CREDENTIALS:" + ",".join(missing))
        print("No network action executed.")
        return 3
    print("Runner contract valid. Live scenario execution must be invoked by an operator with explicit TESTNET credentials.")
    print(offline_runner_contract_summary())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

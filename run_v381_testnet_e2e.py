#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v381 import BinanceTestnetE2EHarnessV381, BinanceTestnetLivePreflightV381


def main() -> int:
    local = BinanceTestnetE2EHarnessV381().run()
    live = BinanceTestnetLivePreflightV381().run()
    payload = {
        "artifact_type": "V381_TESTNET_E2E_EVIDENCE",
        "schema_version": "V381_TESTNET_E2E_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "local_e2e": local.payload(),
        "live_preflight": live,
        "mutating_testnet_order_executed": False,
        "production_ready": False,
        "external_references": [
            "https://www.binance.com/en/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a",
            "https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams",
            "https://developers.binance.com/zh-CN/docs/products/derivatives-trading-coin-futures/change-log",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    out = ROOT / "V381_TESTNET_E2E_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(out)
    print(payload["evidence_hash"])
    print(json.dumps(live, sort_keys=True))
    return 0 if local.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

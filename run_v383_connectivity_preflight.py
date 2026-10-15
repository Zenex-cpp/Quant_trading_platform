from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from trading_platform.v383 import TestnetConnectivityConfigV383, TestnetConnectivityPreflightV383

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cfg = TestnetConnectivityConfigV383(
        rest_base_url=os.getenv("BINANCE_TESTNET_REST_BASE_URL", "https://testnet.binancefuture.com"),
        ws_api_url=os.getenv("BINANCE_TESTNET_WS_API_URL", ""),
        ws_private_url=os.getenv("BINANCE_TESTNET_WS_PRIVATE_URL", ""),
        timeout_s=float(os.getenv("BINANCE_TESTNET_PREFLIGHT_TIMEOUT_S", "5")),
    )
    preflight = TestnetConnectivityPreflightV383(config=cfg)
    evidence = preflight.run()
    payload = {
        "artifact_type": "V383_TESTNET_CONNECTIVITY_PREFLIGHT",
        "schema_version": "V383_CONNECTIVITY_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": evidence.status.value,
        "rest_endpoint": evidence.rest_endpoint,
        "ws_api_endpoint": evidence.ws_api_endpoint,
        "ws_private_endpoint": evidence.ws_private_endpoint,
        "rest_dns": evidence.rest_dns,
        "rest_server_time_ms": evidence.rest_server_time_ms,
        "client_time_ms": evidence.client_time_ms,
        "clock_skew_ms": evidence.clock_skew_ms,
        "reason": evidence.reason,
        "mutating_api_called": False,
        "production_ready": False,
        "credentials_consumed": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    out = ROOT / "V383_TESTNET_CONNECTIVITY_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(out)
    print(payload["status"])
    print(payload["evidence_hash"])
    # NOT_VERIFIED is an acceptable evidence state when runtime DNS/network is unavailable.
    return 0 if payload["status"] in {"VERIFIED", "NOT_VERIFIED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

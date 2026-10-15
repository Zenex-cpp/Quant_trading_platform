#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v383_connectivity import (  # noqa: E402
    PreflightStatus,
    TestnetConnectivityConfigV383,
    TestnetConnectivityPreflightV383,
)


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-only", action="store_true", default=False)
    args = parser.parse_args()
    if not args.probe_only:
        parser.error("V3.88 verification runner is intentionally probe-only")

    cfg = TestnetConnectivityConfigV383(
        environment="TESTNET",
        rest_base_url="https://testnet.binancefuture.com",
        ws_api_url="",
        ws_private_url="wss://fstream.binancefuture.com/private",
    )
    evidence = TestnetConnectivityPreflightV383(config=cfg).run()
    payload = {
        "artifact_type": "V388_FIRST_TESTNET_EVIDENCE_PREFLIGHT",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "connectivity_status": evidence.status.value,
        "rest_endpoint": evidence.rest_endpoint,
        "ws_private_endpoint": evidence.ws_private_endpoint,
        "rest_dns": evidence.rest_dns,
        "reason": evidence.reason,
        "external_testnet_execution": "NOT_VERIFIED",
        "mutating_api_called": False,
        "submit_performed": False,
        "evidence_closure": "IMPLEMENTED_AND_LOCALLY_TESTED",
        "production_ready": False,
    }
    payload["evidence_hash"] = canonical_hash(payload)
    out = ROOT / "V388_FIRST_TESTNET_EVIDENCE_PREFLIGHT.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    print(evidence.status.value, evidence.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

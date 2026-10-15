#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v389 import TestnetRuntimeCredentialAuthorityV389, TestnetCredentialErrorV389


def main() -> int:
    now = datetime.now(timezone.utc)
    try:
        cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(
            now=now,
            endpoint="https://testnet.binancefuture.com",
        )
        status = "VERIFIED"
        reason = "DEDICATED_TESTNET_CREDENTIAL_CAPABILITY_ISSUED"
        metadata = cap.metadata.safe_payload()
    except TestnetCredentialErrorV389 as exc:
        status = "NOT_VERIFIED"
        reason = str(exc)
        metadata = None
    payload = {
        "artifact_type": "V389_TESTNET_CREDENTIAL_PREFLIGHT",
        "retrieved_at": now.isoformat(),
        "status": status,
        "reason": reason,
        "metadata": metadata,
        "raw_credentials_persisted": False,
        "mutating_api_called": False,
        "external_testnet_execution": "NOT_VERIFIED",
        "production_ready": False,
    }
    out = ROOT / "V389_PREFLIGHT_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    print(status, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

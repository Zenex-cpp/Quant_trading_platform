from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from trading_platform.v390 import TestnetEgressAuthorityV390, EgressBoundaryErrorV390


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    evidence = {
        "artifact_type": "V390_TESTNET_EGRESS_PREFLIGHT",
        "retrieved_at": now,
        "mutating_api_called": False,
        "production_ready": False,
    }
    env = dict(os.environ)
    try:
        authority = TestnetEgressAuthorityV390(environ=env)
        payload = authority.authorization_payload(endpoint="https://testnet.binancefuture.com")
    except EgressBoundaryErrorV390 as exc:
        evidence.update({
            "status": "NOT_VERIFIED",
            "application_egress_boundary": "VERIFIED",
            "credential_release_allowed": False,
            "reason": str(exc),
        })
    else:
        evidence.update({
            "status": "READY_FOR_NETWORK_PROBE",
            "application_egress_boundary": "VERIFIED",
            "credential_release_allowed": True,
            "authorization_payload": payload,
        })
    Path("V390_PREFLIGHT_EVIDENCE.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

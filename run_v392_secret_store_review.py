from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v392.secret_store_operational import (  # noqa: E402
    SecretLeaseV392,
    SecretStoreAttestationV392,
    SecretStoreBackendV392,
    SecretStoreOperationalPolicyV392,
    assert_production_secret_store_ready,
    configuration_fingerprint,
)

now = 1_000_000
attestation = SecretStoreAttestationV392(
    backend=SecretStoreBackendV392.EXTERNAL_VAULT,
    backend_id="review-fixture-vault",
    backend_version="fixture-1",
    attested_at_ms=now - 1_000,
    expires_at_ms=now + 86_400_000,
    configuration_fingerprint=configuration_fingerprint({"fixture": "review-only", "environment": "production"}),
    reviewer_id="fixture-reviewer",
    review_reference="V392-APP-CONTRACT-ONLY",
)
lease = SecretLeaseV392(
    lease_id="review-fixture-lease",
    credential_id="production-fixture",
    version="v1",
    backend=SecretStoreBackendV392.EXTERNAL_VAULT,
    issued_at_ms=now - 1_000,
    expires_at_ms=now + 900_000,
    credential_fingerprint="0" * 64,
)
decision = assert_production_secret_store_ready(
    policy=SecretStoreOperationalPolicyV392(),
    attestation=attestation,
    lease=lease,
    now_ms=now,
)
evidence = {
    "evidence_id": "V392-SECRET-STORE-PREFLIGHT-001",
    "decision": decision.safe_payload(),
    "external_deployment_proof": "NOT_VERIFIED",
    "production_credential_access": "NOT_PERFORMED",
}
(ROOT / "V392_SECRET_STORE_PREFLIGHT_EVIDENCE.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(evidence, indent=2, sort_keys=True))

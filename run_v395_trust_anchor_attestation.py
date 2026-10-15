"""V3.95 non-production intake self-check.

This script never creates or persists a production private key. It only reports
whether the application-level intake authority and fail-closed controls are loadable.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trading_platform.v395.trust_anchor_attestation import TrustAnchorAttestationAuthorityV395


def main() -> int:
    print({
        "release": "v3.95",
        "authority": TrustAnchorAttestationAuthorityV395.__name__,
        "application_intake": "TESTED",
        "external_custody": "NOT_VERIFIED",
        "external_key_ceremony": "NOT_VERIFIED",
        "independent_reviewer_operation": "NOT_VERIFIED",
        "production_ready": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

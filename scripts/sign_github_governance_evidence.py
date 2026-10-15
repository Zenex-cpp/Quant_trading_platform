#!/usr/bin/env python3
"""Sign a captured provider snapshot using an external Ed25519 PEM key.

Run only on the independent reviewer's system. Private key path must be outside
this checkout and is never copied into the package. Signing is not validation.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import time
import stat

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from trading_platform.v21.event_store import canonical_json
from trading_platform.v429.external_file_safety import (
    ExternalFileSafetyErrorV429,
    read_external_regular_file_v429,
    resolve_external_output_v429,
    write_external_new_file_v429,
)

ROLE = "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--private-key-pem", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--signer-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--now-ms", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        key_path, key_bytes, key_stat = read_external_regular_file_v429(
            ROOT, args.private_key_pem, label="PRIVATE_KEY", max_bytes=1 * 1024 * 1024,
        )
        evidence_path, evidence_bytes, _ = read_external_regular_file_v429(
            ROOT, args.evidence, label="EVIDENCE", max_bytes=16 * 1024 * 1024,
        )
        output_path = resolve_external_output_v429(
            ROOT, args.output, label="SIGNED_EVIDENCE",
            protected_inputs={"evidence": evidence_path, "private_key": key_path},
        )
    except ExternalFileSafetyErrorV429 as exc:
        parser.error(f"PATH_POLICY_REJECTED:{exc}")
    if key_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        parser.error("PRIVATE_KEY_PERMISSIONS_TOO_OPEN_USE_MODE_0600_OR_STRICTER")
    if not args.key_id.strip() or not args.signer_id.strip():
        parser.error("KEY_ID_AND_SIGNER_ID_REQUIRED")
    try:
        payload = json.loads(evidence_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            parser.error("UNSIGNED_V424_PAYLOAD_REQUIRED")
        payload.pop("attestation", None)
        key = serialization.load_pem_private_key(key_bytes, password=None)
    except SystemExit:
        raise
    except Exception:
        parser.error("EVIDENCE_OR_PRIVATE_KEY_CANNOT_BE_READ")
    if not isinstance(payload, dict) or payload.get("schema_version") != "V4.24":
        parser.error("UNSIGNED_V424_PAYLOAD_REQUIRED")
    if not isinstance(key, Ed25519PrivateKey):
        parser.error("ED25519_PRIVATE_KEY_REQUIRED")
    captured = int(payload.get("captured_at_ms", 0))
    payload_expires = int(payload.get("expires_at_ms", 0))
    now = args.now_ms if args.now_ms is not None else time.time_ns() // 1_000_000
    if captured <= 0 or captured > now or payload_expires <= now:
        parser.error("EVIDENCE_CAPTURE_OR_EXPIRY_INVALID")
    if payload_expires - captured > 86_400_000:
        parser.error("EVIDENCE_TTL_EXCEEDS_ONE_DAY_MAXIMUM")
    attestation = {
        "key_id": args.key_id,
        "signer_id": args.signer_id,
        "signer_role": ROLE,
        "signed_at_ms": int(now),
        "expires_at_ms": payload_expires,
    }
    signature = key.sign(canonical_json({"payload": payload, "attestation": attestation}))
    signed = {**payload, "attestation": {**attestation, "signature_b64": base64.b64encode(signature).decode("ascii")}}
    try:
        # Use the original CLI path again so the write operation revalidates
        # every directory component and creates the destination with O_EXCL.
        write_external_new_file_v429(
            ROOT, args.output, json.dumps(signed, indent=2, sort_keys=True) + "\n",
            label="SIGNED_EVIDENCE",
            protected_inputs={"evidence": evidence_path, "private_key": key_path},
        )
    except ExternalFileSafetyErrorV429 as exc:
        parser.error(f"PATH_POLICY_REJECTED:{exc}")
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    from hashlib import sha256
    print("GITHUB_GOVERNANCE_EVIDENCE=SIGNED")
    print(f"SIGNER_ROLE={ROLE}")
    print(f"PUBLIC_KEY_SHA256={sha256(public).hexdigest()}")
    print("TRUST_ANCHOR_CONFIGURATION=REQUIRES_SEPARATE_INDEPENDENT_APPROVAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

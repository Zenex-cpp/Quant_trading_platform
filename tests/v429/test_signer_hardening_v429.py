from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]


def _payload() -> dict:
    return {
        "schema_version": "V4.24",
        "snapshot_id": "synthetic-snapshot",
        "provider": "github",
        "repository": "acme/trading-platform",
        "protected_branch": "main",
        "protected_head_sha": "a" * 40,
        "captured_at_ms": 1_850_000_000_000,
        "expires_at_ms": 1_850_000_060_000,
    }


def _key_file(path: Path, mode: int = 0o600) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    path.chmod(mode)
    return key


def _run(evidence: Path, key: Path, output: Path, *, now: int = 1_850_000_010_000):
    return subprocess.run(
        [sys.executable, "scripts/sign_github_governance_evidence.py",
         "--evidence", str(evidence), "--private-key-pem", str(key),
         "--key-id", "independent-key-1", "--signer-id", "independent-reviewer-1",
         "--output", str(output), "--now-ms", str(now)],
        cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        shell=False, check=False, capture_output=True, text=True,
    )


def test_v429_signer_rejects_key_in_symlinked_parent_before_signing(tmp_path: Path):
    review = tmp_path / "review"
    review.mkdir(mode=0o700)
    key = review / "key.pem"
    _key_file(key)
    alias = tmp_path / "key-alias"
    alias.symlink_to(review, target_is_directory=True)
    evidence = tmp_path / "unsigned.json"
    evidence.write_text(json.dumps(_payload()), encoding="utf-8")
    output = tmp_path / "signed.json"

    result = _run(evidence, alias / "key.pem", output)
    assert result.returncode != 0
    assert "PARENT_COMPONENT_UNSAFE" in result.stderr
    assert not output.exists()


def test_v429_signer_rejects_evidence_in_symlinked_parent(tmp_path: Path):
    review = tmp_path / "review"
    review.mkdir(mode=0o700)
    key = tmp_path / "key.pem"
    _key_file(key)
    evidence = review / "unsigned.json"
    evidence.write_text(json.dumps(_payload()), encoding="utf-8")
    alias = tmp_path / "evidence-alias"
    alias.symlink_to(review, target_is_directory=True)
    output = tmp_path / "signed.json"

    result = _run(alias / "unsigned.json", key, output)
    assert result.returncode != 0
    assert "PARENT_COMPONENT_UNSAFE" in result.stderr
    assert not output.exists()


def test_v429_signer_never_overwrites_existing_output(tmp_path: Path):
    key = tmp_path / "key.pem"
    _key_file(key)
    evidence = tmp_path / "unsigned.json"
    evidence.write_text(json.dumps(_payload()), encoding="utf-8")
    output = tmp_path / "signed.json"
    output.write_text("preserve-original\n", encoding="utf-8")

    result = _run(evidence, key, output)
    assert result.returncode != 0
    assert "OUTPUT_ALREADY_EXISTS" in result.stderr or "OUTPUT_CREATE_FAILED_OR_ALREADY_EXISTS" in result.stderr
    assert output.read_text(encoding="utf-8") == "preserve-original\n"


def test_v429_signer_success_creates_exclusive_output_mode_0600_and_valid_signature(tmp_path: Path):
    key = tmp_path / "key.pem"
    private = _key_file(key)
    evidence = tmp_path / "unsigned.json"
    evidence.write_text(json.dumps(_payload()), encoding="utf-8")
    output = tmp_path / "signed.json"
    result = _run(evidence, key, output)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (output.stat().st_mode & 0o777) == 0o600
    signed = json.loads(output.read_text(encoding="utf-8"))
    attestation = dict(signed.pop("attestation"))
    signature = base64.b64decode(attestation.pop("signature_b64"), validate=True)
    from trading_platform.v21.event_store import canonical_json
    public = private.public_key()
    public.verify(signature, canonical_json({"payload": signed, "attestation": attestation}))


def test_v429_signer_bounds_unsigned_evidence_before_json_parse(tmp_path: Path):
    key = tmp_path / "key.pem"
    _key_file(key)
    evidence = tmp_path / "unsigned.json"
    evidence.write_bytes(b" " * (16 * 1024 * 1024 + 1))
    output = tmp_path / "signed.json"
    result = _run(evidence, key, output)
    assert result.returncode != 0
    assert "EVIDENCE_FILE_SIZE_LIMIT_EXCEEDED" in result.stderr
    assert not output.exists()

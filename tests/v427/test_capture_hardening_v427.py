from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v425.github_capture import (
    GitHubGovernanceCaptureErrorV425,
    decode_github_content_v425,
)
from trading_platform.v427.capture_hardening import (
    CaptureHardeningErrorV427,
    MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427,
    MAX_GOVERNANCE_JSON_BYTES_V427,
    MAX_PREFLIGHT_SQLITE_BYTES_V427,
    validate_capture_artifact_size_v427,
)


def response(content: str) -> dict[str, str]:
    return {"type": "file", "encoding": "base64", "path": ".github/CODEOWNERS", "content": content}


def test_v427_accepts_github_base64_wrapped_with_whitespace():
    body = b"/.github/CODEOWNERS @acme/platform-maintainers\n"
    encoded = base64.b64encode(body).decode("ascii")
    wrapped = encoded[:12] + "\n " + encoded[12:] + "\t"
    assert decode_github_content_v425(response(wrapped), path=".github/CODEOWNERS") == body


@pytest.mark.parametrize("content", ["aG VsbG8h!", "!!!!", "aGVsbG8"])
def test_v427_rejects_non_base64_garbage_and_bad_padding(content: str):
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="REMOTE_FILE_CONTENT_INVALID"):
        decode_github_content_v425(response(content), path=".github/CODEOWNERS")


def test_v427_rejects_non_ascii_in_base64_content():
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="REMOTE_FILE_CONTENT_INVALID"):
        decode_github_content_v425(response("aGVsbG8=é"), path=".github/CODEOWNERS")


def test_v427_artifact_size_bounds_accept_exact_total_limit():
    total = validate_capture_artifact_size_v427(
        "V425_MILESTONE_PREFLIGHT.json", MAX_GOVERNANCE_JSON_BYTES_V427
    )
    total = validate_capture_artifact_size_v427(
        "V425_MILESTONE_PREFLIGHT.sqlite3", MAX_PREFLIGHT_SQLITE_BYTES_V427,
        total_so_far_bytes=total,
    )
    assert total == MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("V425_MILESTONE_PREFLIGHT.json", MAX_GOVERNANCE_JSON_BYTES_V427 + 1),
        ("V425_MILESTONE_PREFLIGHT.sqlite3", MAX_PREFLIGHT_SQLITE_BYTES_V427 + 1),
        ("untrusted.zip", 100),
        ("V425_MILESTONE_PREFLIGHT.json", 0),
    ],
)
def test_v427_rejects_oversized_empty_or_unexpected_artifacts(name: str, size: int):
    with pytest.raises(CaptureHardeningErrorV427):
        validate_capture_artifact_size_v427(name, size)


def test_v427_rejects_cumulative_capture_size_over_limit():
    with pytest.raises(CaptureHardeningErrorV427, match="CAPTURE_ARTIFACT_TOTAL_LIMIT_EXCEEDED"):
        validate_capture_artifact_size_v427(
            "V425_MILESTONE_PREFLIGHT.sqlite3", 1,
            total_so_far_bytes=MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427,
        )


def test_v427_source_contract_uses_strict_base64_and_bounded_artifact_reads():
    src = (ROOT / "src/trading_platform/v427/capture_hardening.py").read_text(encoding="utf-8")
    script = (ROOT / "scripts/capture_github_governance.py").read_text(encoding="utf-8")
    assert "validate=True" in src
    assert "MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427" in src
    assert "validate_capture_artifact_size_v427" in script
    assert "stream.read(limit + 1)" in script
    assert "shell=False" in script

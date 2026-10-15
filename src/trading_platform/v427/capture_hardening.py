"""Strict parsing and resource bounds for remote GitHub governance capture.

This module does not access the network or execute subprocesses. It hardens the
untrusted response/artifact boundary used by the V4.25 recovery capture flow.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Mapping


class CaptureHardeningErrorV427(ValueError):
    __test__ = False


MAX_GOVERNANCE_JSON_BYTES_V427 = 16 * 1024 * 1024
MAX_PREFLIGHT_SQLITE_BYTES_V427 = 64 * 1024 * 1024
MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427 = 80 * 1024 * 1024
_ARTIFACT_LIMITS_V427 = {
    "V425_MILESTONE_PREFLIGHT.json": MAX_GOVERNANCE_JSON_BYTES_V427,
    "V425_MILESTONE_PREFLIGHT.sqlite3": MAX_PREFLIGHT_SQLITE_BYTES_V427,
}


def decode_github_content_strict_v427(response: Mapping[str, Any], *, path: str) -> bytes:
    """Decode GitHub's Base64 content field strictly, permitting whitespace only.

    GitHub may line-wrap the Base64 field. Whitespace is removed, but all other
    non-Base64 characters, incorrect padding, non-ASCII values and empty decoded
    content are rejected.
    """
    if response.get("type") != "file" or response.get("encoding") != "base64":
        raise CaptureHardeningErrorV427(f"REMOTE_FILE_NOT_BASE64_FILE:{path}")
    if str(response.get("path", "")) != path:
        raise CaptureHardeningErrorV427(f"REMOTE_FILE_PATH_MISMATCH:{path}")
    raw_content = response.get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise CaptureHardeningErrorV427(f"REMOTE_FILE_CONTENT_MISSING:{path}")
    compact = "".join(raw_content.split())
    try:
        encoded = compact.encode("ascii", errors="strict")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error, TypeError):
        raise CaptureHardeningErrorV427(f"REMOTE_FILE_CONTENT_INVALID:{path}") from None
    if not decoded:
        raise CaptureHardeningErrorV427(f"REMOTE_FILE_CONTENT_EMPTY:{path}")
    return decoded


def validate_capture_artifact_size_v427(name: str, size_bytes: int, *, total_so_far_bytes: int = 0) -> int:
    """Validate a captured audit artifact size and return the updated total."""
    if name not in _ARTIFACT_LIMITS_V427:
        raise CaptureHardeningErrorV427("UNEXPECTED_CAPTURE_ARTIFACT_NAME")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
        raise CaptureHardeningErrorV427(f"CAPTURE_ARTIFACT_SIZE_INVALID:{name}")
    if size_bytes > _ARTIFACT_LIMITS_V427[name]:
        raise CaptureHardeningErrorV427(f"CAPTURE_ARTIFACT_SIZE_LIMIT_EXCEEDED:{name}")
    if isinstance(total_so_far_bytes, bool) or not isinstance(total_so_far_bytes, int) or total_so_far_bytes < 0:
        raise CaptureHardeningErrorV427("CAPTURE_ARTIFACT_TOTAL_INVALID")
    total = total_so_far_bytes + size_bytes
    if total > MAX_CAPTURE_ARTIFACT_TOTAL_BYTES_V427:
        raise CaptureHardeningErrorV427("CAPTURE_ARTIFACT_TOTAL_LIMIT_EXCEEDED")
    return total

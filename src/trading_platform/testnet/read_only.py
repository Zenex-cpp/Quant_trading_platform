from __future__ import annotations

from urllib.parse import urlsplit


def normalize_read_only_request(method: str, path: str) -> str:
    """Validate a request exposed by a read-only Testnet evidence runner."""
    if not isinstance(method, str) or method.upper() != "GET":
        raise PermissionError("TESTNET_READ_ONLY_METHOD_REQUIRED")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise PermissionError("TESTNET_READ_ONLY_PATH_INVALID")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path != path:
        raise PermissionError("TESTNET_READ_ONLY_PATH_INVALID")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in path):
        raise PermissionError("TESTNET_READ_ONLY_PATH_INVALID")
    return "GET"

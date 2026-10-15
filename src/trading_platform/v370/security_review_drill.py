from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import re

FORBIDDEN_FILENAMES = {
    ".env", ".env.local", ".env.production", "credentials.json", "secrets.json",
    "id_rsa", "id_ed25519", "server.key", "server.pem",
}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks"}
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
HARDCODED_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?secret|private[_-]?key|secret[_-]?key)\s*[:=]\s*['\"]([^'\"]{12,})['\"]"
)
PRODUCTION_ENDPOINT_RE = re.compile(
    r"(?i)\b(?:https?://|wss?://)?(?:api|fapi|dapi|fstream|ws-fapi)\.binance\.com\b"
)
FORBIDDEN_NETWORK_IMPORTS = (
    "import requests", "import httpx", "import socket", "import websocket",
    "import aiohttp", "from urllib.request import", "urlopen(",
)


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    detail: str
    fingerprint: str


def _fingerprint(category: str, path: str, detail: str) -> str:
    return hashlib.sha256(f"{category}|{path}|{detail}".encode()).hexdigest()


def _iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            try:
                yield path, path.read_text(errors="ignore")
            except OSError:
                continue


def run_security_review_drill(root: str | Path) -> dict:
    root = Path(root).resolve()
    findings: list[Finding] = []
    source_root = root / "src" / "trading_platform"
    if not source_root.exists():
        findings.append(Finding("STRUCTURE", "src/trading_platform", "missing source root", _fingerprint("STRUCTURE", "src/trading_platform", "missing source root")))

    scan_roots = [source_root, root / "pyproject.toml", root / "README.md"]
    candidates = []
    for scan_root in scan_roots:
        if scan_root.is_file():
            candidates.append(scan_root)
        elif scan_root.exists():
            candidates.extend(p for p in sorted(scan_root.rglob("*")) if p.is_file())
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        if path.name.lower() in FORBIDDEN_FILENAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(Finding("SECRET_PATH", rel, "forbidden secret-like file", _fingerprint("SECRET_PATH", rel, "forbidden secret-like file")))
        if PRIVATE_KEY_RE.search(text):
            findings.append(Finding("PRIVATE_KEY", rel, "private key material marker", _fingerprint("PRIVATE_KEY", rel, "private key material marker")))
        if HARDCODED_SECRET_RE.search(text):
            findings.append(Finding("HARDCODED_SECRET", rel, "credential-like assignment", _fingerprint("HARDCODED_SECRET", rel, "credential-like assignment")))

    if source_root.exists():
        research_root = source_root / "research"
        if research_root.exists():
            for path in sorted(research_root.rglob("*.py")):
                text = path.read_text(errors="ignore")
                for token in FORBIDDEN_NETWORK_IMPORTS:
                    if token in text:
                        rel = str(path.relative_to(root))
                        findings.append(Finding("RESEARCH_NETWORK_IMPORT", rel, token, _fingerprint("RESEARCH_NETWORK_IMPORT", rel, token)))
                for match in PRODUCTION_ENDPOINT_RE.findall(text):
                    rel = str(path.relative_to(root))
                    findings.append(Finding("RESEARCH_PRODUCTION_ENDPOINT", rel, match, _fingerprint("RESEARCH_PRODUCTION_ENDPOINT", rel, match)))

    findings = sorted({f.fingerprint: f for f in findings}.values(), key=lambda f: (f.category, f.path, f.detail))
    return {
        "schema_version": "V370_SECURITY_DRILL_1",
        "source_kind": "INTERNAL",
        "scope": "REPOSITORY_RELEASE_ARTIFACT",
        "root": str(root),
        "status": "PASS" if not findings else "FAIL",
        "finding_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }

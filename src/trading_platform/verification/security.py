from __future__ import annotations
import re
from pathlib import Path
from .durable import *

SECRET_PATTERNS=(re.compile(r'AKIA[0-9A-Z]{16}'), re.compile(r'(?i)(api[_-]?secret|private[_-]?key|secret[_-]?key)\s*[:=]\s*["\']?[A-Za-z0-9+/=_-]{20,}'))

def scan_secrets(root: str|Path)->list[str]:
    findings=[]; root=Path(root)
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix in {'.pyc','.tar.gz'}: continue
        try: text=p.read_text(errors='ignore')
        except OSError: continue
        for pat in SECRET_PATTERNS:
            if pat.search(text): findings.append(str(p.relative_to(root))) ; break
    return sorted(set(findings))

def research_network_allowed(endpoint: str)->bool:
    e=endpoint.lower()
    production_markers=('fapi.binance.com','api.binance.com','dapi.binance.com')
    return not any(x in e for x in production_markers)

def assert_research_boundary(endpoint: str)->None:
    if not research_network_allowed(endpoint): raise PermissionError('RESEARCH_TO_PRODUCTION_NETWORK_FORBIDDEN')

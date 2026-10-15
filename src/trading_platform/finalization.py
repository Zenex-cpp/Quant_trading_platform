from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json

def deterministic_id(prefix:str, payload:object)->str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()
    return f"{prefix}:{sha256(raw).hexdigest()[:24]}"

def production_entry_allowed(*, readiness: bool, promotion: bool, approval: bool, kill_switch: bool, reconciliation_ok: bool)->bool:
    return all((readiness,promotion,approval,not kill_switch,reconciliation_ok))

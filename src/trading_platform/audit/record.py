from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

@dataclass(frozen=True)
class AuditRecord:
    audit_id: str
    event_type: str
    timestamp: datetime
    actor: str
    payload: dict
    previous_hash: str | None=None

    def content_hash(self) -> str:
        b=json.dumps(self.payload,sort_keys=True,separators=(",",":"),default=str).encode()
        return sha256(((self.previous_hash or "")+self.event_type+self.timestamp.isoformat()+b.decode()).encode()).hexdigest()

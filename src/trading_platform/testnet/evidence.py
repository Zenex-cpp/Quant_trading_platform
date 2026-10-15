from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib, json
from enum import Enum

class EvidenceStatus(str, Enum):
    PASS="PASS"; FAIL="FAIL"; NOT_VERIFIED="NOT_VERIFIED"

@dataclass(frozen=True)
class TestnetEvidence:
    __test__ = False
    evidence_id: str
    scenario_id: str
    status: EvidenceStatus
    started_at: str
    completed_at: str
    environment: str
    references: tuple[str,...]
    observations: tuple[str,...]
    artifact_hash: str | None = None

    def canonical_bytes(self) -> bytes:
        data=asdict(self)
        data.pop("artifact_hash", None)
        return json.dumps(data, sort_keys=True, separators=(",",":"), default=lambda x: x.value if isinstance(x, Enum) else x).encode()

    def with_hash(self) -> "TestnetEvidence":
        h=hashlib.sha256(self.canonical_bytes()).hexdigest()
        return TestnetEvidence(**{**asdict(self), "status": self.status, "artifact_hash": h})

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat()

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

@dataclass(frozen=True)
class ReplayCheckpoint:
    event_offset: int
    snapshot_version: str
    state_hash: str


def canonical_hash(state: Any) -> str:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()

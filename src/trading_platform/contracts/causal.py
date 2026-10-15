from dataclasses import dataclass
from datetime import datetime
from typing import FrozenSet
from trading_platform.core.ttl import ValidWindow

@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    version: str
    state: str
    window: ValidWindow
    dependencies: FrozenSet[str]


def validate_upstream(required: FrozenSet[ArtifactRef], now: datetime) -> None:
    for ref in required:
        if ref.state not in {"VALID", "APPROVED", "ACTIVE"}:
            raise ValueError(f"INVALID_UPSTREAM_STATE:{ref.artifact_id}")
        ref.window.assert_valid(now)

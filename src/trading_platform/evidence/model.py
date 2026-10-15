from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class EvidenceState(str, Enum):
    VALID="VALID"
    SUSPENDED="SUSPENDED"
    INVALIDATED="INVALIDATED"
    REVALIDATED="REVALIDATED"
    EXPIRED="EXPIRED"

@dataclass(frozen=True)
class EvidenceSnapshot:
    snapshot_id: str
    evidence_ids: tuple[str,...]
    metrics_hash: str
    dependency_graph_version: str
    gate_results_hash: str
    approvals_hash: str
    created_at: datetime
    content_hash: str

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib, json, sqlite3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode('utf-8')

@dataclass(frozen=True)
class EvidenceArtifact:
    evidence_id: str
    scenario_id: str
    status: str
    environment: str
    started_at: str
    completed_at: str
    correlation_id: str
    operator_id: str
    endpoint: str
    request_hash: str | None
    response_hash: str | None
    pre_snapshot_hash: str | None
    post_snapshot_hash: str | None
    reconciliation: str
    observations: tuple[str, ...]
    references: tuple[str, ...]
    artifact_hash: str | None = None

    def canonical_body(self) -> bytes:
        data = asdict(self)
        data.pop('artifact_hash', None)
        return canonical_json(data)

    def sealed(self) -> 'EvidenceArtifact':
        h = hashlib.sha256(self.canonical_body()).hexdigest()
        return EvidenceArtifact(**{**asdict(self), 'artifact_hash': h})

class DurableEvidenceStore:
    """Append-only SQLite evidence store; duplicate IDs are idempotent."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                status TEXT NOT NULL,
                environment TEXT NOT NULL,
                payload BLOB NOT NULL,
                artifact_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )''')
            db.execute("""CREATE TRIGGER IF NOT EXISTS deny_evidence_update
            BEFORE UPDATE ON evidence BEGIN
                SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_UPDATE_FORBIDDEN');
            END;""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS deny_evidence_delete
            BEFORE DELETE ON evidence BEGIN
                SELECT RAISE(ABORT, 'IMMUTABLE_RECORD_DELETE_FORBIDDEN');
            END;""")
            db.commit()

    def append(self, artifact: EvidenceArtifact) -> EvidenceArtifact:
        if artifact.artifact_hash is None:
            artifact = artifact.sealed()
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload, artifact_hash FROM evidence WHERE evidence_id=?', (artifact.evidence_id,)).fetchone()
            payload = artifact.canonical_body()
            if row:
                if row[1] != artifact.artifact_hash or row[0] != payload:
                    raise ValueError('EVIDENCE_ID_REUSE_WITH_DIFFERENT_PAYLOAD')
                return artifact
            db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)', (
                artifact.evidence_id, artifact.scenario_id, artifact.status, artifact.environment,
                payload, artifact.artifact_hash, artifact.created_at if hasattr(artifact, 'created_at') else utc_now()))
            db.commit()
        return artifact

    def verify(self) -> tuple[str, ...]:
        failures=[]
        with sqlite3.connect(self.path) as db:
            for evidence_id, payload, artifact_hash in db.execute('SELECT evidence_id,payload,artifact_hash FROM evidence'):
                if hashlib.sha256(payload).hexdigest() != artifact_hash:
                    failures.append(evidence_id)
        return tuple(failures)

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json

@dataclass(frozen=True)
class EvidenceSnapshot:
    snapshot_id: str
    evidence_ids: tuple[str,...]
    metrics_hash: str
    gates: tuple[str,...]
    dependencies: tuple[str,...]
    versions: tuple[str,...]
    hashes: tuple[str,...]
    methodology: tuple[str,...]
    approvals: tuple[str,...]
    scope: dict[str,str]
    content_hash: str
    metrics: object = None

def snapshot_payload(snapshot: EvidenceSnapshot) -> dict:
    return {
        'snapshot_id':snapshot.snapshot_id,
        'evidence_ids':snapshot.evidence_ids,
        'metrics':snapshot.metrics,
        'gates':snapshot.gates,
        'dependencies':snapshot.dependencies,
        'versions':snapshot.versions,
        'hashes':snapshot.hashes,
        'methodology':snapshot.methodology,
        'approvals':snapshot.approvals,
        'scope':snapshot.scope,
    }

def snapshot_content_hash(snapshot: EvidenceSnapshot) -> str:
    return sha256(json.dumps(snapshot_payload(snapshot),sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

def build_snapshot(snapshot_id: str, evidence_ids: tuple[str,...], metrics: object, gates: tuple[str,...], dependencies: tuple[str,...], versions: tuple[str,...], hashes: tuple[str,...], methodology: tuple[str,...], approvals: tuple[str,...], scope: dict[str,str]) -> EvidenceSnapshot:
    payload=snapshot_payload(EvidenceSnapshot(snapshot_id,evidence_ids,'',gates,dependencies,versions,hashes,methodology,approvals,scope,'' ,metrics))
    content_hash=sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    metric_hash=sha256(json.dumps(metrics,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    return EvidenceSnapshot(snapshot_id,evidence_ids,metric_hash,gates,dependencies,versions,hashes,methodology,approvals,scope,content_hash,metrics)

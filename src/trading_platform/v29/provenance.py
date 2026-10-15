from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable

class ProvenanceEventType(str, Enum):
    RELEASE_CREATED = "RELEASE_CREATED"
    APPROVAL_ATTACHED = "APPROVAL_ATTACHED"
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
    CONFIG_FINGERPRINTED = "CONFIG_FINGERPRINTED"
    DEPLOYMENT_LINKED = "DEPLOYMENT_LINKED"
    ROLLBACK_LINKED = "ROLLBACK_LINKED"
    RELEASE_REVOKED = "RELEASE_REVOKED"

@dataclass(frozen=True)
class ProvenanceEvent:
    sequence: int
    event_type: ProvenanceEventType
    release_id: str
    actor: str
    reference_id: str
    reason: str
    timestamp_ns: int
    previous_hash: str
    event_hash: str

    @staticmethod
    def build(*, sequence:int, event_type:ProvenanceEventType, release_id:str, actor:str,
              reference_id:str, reason:str, timestamp_ns:int, previous_hash:str) -> "ProvenanceEvent":
        if sequence < 1 or not release_id or not actor or not reference_id or not reason:
            raise ValueError("PROVENANCE_EVENT_FIELDS_REQUIRED")
        payload={"sequence":sequence,"event_type":event_type.value,"release_id":release_id,
                 "actor":actor,"reference_id":reference_id,"reason":reason,
                 "timestamp_ns":timestamp_ns,"previous_hash":previous_hash}
        h=sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return ProvenanceEvent(sequence,event_type,release_id,actor,reference_id,reason,timestamp_ns,previous_hash,h)

    def verify(self, previous_hash:str)->bool:
        expected=self.build(sequence=self.sequence,event_type=self.event_type,release_id=self.release_id,
                            actor=self.actor,reference_id=self.reference_id,reason=self.reason,
                            timestamp_ns=self.timestamp_ns,previous_hash=self.previous_hash).event_hash
        return self.previous_hash==previous_hash and self.event_hash==expected

@dataclass(frozen=True)
class ProvenanceChain:
    events: tuple[ProvenanceEvent,...]=()

    @property
    def head_hash(self)->str:
        return self.events[-1].event_hash if self.events else "GENESIS"

    def append(self,event:ProvenanceEvent)->"ProvenanceChain":
        if event.sequence != len(self.events)+1: raise ValueError("PROVENANCE_SEQUENCE_GAP")
        if not event.verify(self.head_hash): raise ValueError("PROVENANCE_EVENT_INVALID")
        return ProvenanceChain(self.events+(event,))

    def verify(self)->None:
        previous="GENESIS"
        for i,event in enumerate(self.events,1):
            if event.sequence != i or not event.verify(previous): raise ValueError("PROVENANCE_CHAIN_INVALID")
            previous=event.event_hash

@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    artifact_sha256: str
    code_sha256: str
    config_sha256: str
    evidence_ids: tuple[str,...]
    approval_id: str
    deployment_id: str
    created_at_ns: int

    @property
    def fingerprint(self)->str:
        payload={"release_id":self.release_id,"artifact_sha256":self.artifact_sha256,
                 "code_sha256":self.code_sha256,"config_sha256":self.config_sha256,
                 "evidence_ids":list(self.evidence_ids),"approval_id":self.approval_id,
                 "deployment_id":self.deployment_id,"created_at_ns":self.created_at_ns}
        return sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()

@dataclass(frozen=True)
class ProvenanceState:
    manifest: ReleaseManifest
    approval_valid: bool
    evidence_valid: bool
    config_verified: bool
    deployment_linked: bool
    revoked: bool=False

    @property
    def deployable(self)->bool:
        return (not self.revoked and self.approval_valid and self.evidence_valid and
                self.config_verified and self.deployment_linked)

@dataclass(frozen=True)
class ProvenanceLedger:
    state: ProvenanceState
    chain: ProvenanceChain=ProvenanceChain()

    def _event(self, et:ProvenanceEventType, actor:str, ref:str, reason:str, now_ns:int)->ProvenanceEvent:
        return ProvenanceEvent.build(sequence=len(self.chain.events)+1,event_type=et,release_id=self.state.manifest.release_id,
                                     actor=actor,reference_id=ref,reason=reason,timestamp_ns=now_ns,
                                     previous_hash=self.chain.head_hash)

    def attach_approval(self, *, actor:str, valid:bool, approval_id:str, now_ns:int)->"ProvenanceLedger":
        if approval_id != self.state.manifest.approval_id: raise ValueError("APPROVAL_ID_MISMATCH")
        if not valid: raise ValueError("APPROVAL_INVALID")
        e=self._event(ProvenanceEventType.APPROVAL_ATTACHED,actor,approval_id,"APPROVAL_VALIDATED",now_ns)
        return ProvenanceLedger(ProvenanceState(self.state.manifest,True,self.state.evidence_valid,self.state.config_verified,self.state.deployment_linked,self.state.revoked),self.chain.append(e))

    def attach_evidence(self, *, actor:str, evidence_ids:Iterable[str], now_ns:int)->"ProvenanceLedger":
        ids=tuple(sorted(set(evidence_ids)))
        required=set(self.state.manifest.evidence_ids)
        if not required or set(ids) != required: raise ValueError("EVIDENCE_SET_MISMATCH")
        e=self._event(ProvenanceEventType.EVIDENCE_ATTACHED,actor,"|".join(ids),"EVIDENCE_SET_VERIFIED",now_ns)
        return ProvenanceLedger(ProvenanceState(self.state.manifest,self.state.approval_valid,True,self.state.config_verified,self.state.deployment_linked,self.state.revoked),self.chain.append(e))

    def verify_config(self, *, actor:str, observed_sha256:str, now_ns:int)->"ProvenanceLedger":
        if observed_sha256 != self.state.manifest.config_sha256: raise ValueError("CONFIG_FINGERPRINT_MISMATCH")
        e=self._event(ProvenanceEventType.CONFIG_FINGERPRINTED,actor,observed_sha256,"CONFIG_HASH_VERIFIED",now_ns)
        return ProvenanceLedger(ProvenanceState(self.state.manifest,self.state.approval_valid,self.state.evidence_valid,True,self.state.deployment_linked,self.state.revoked),self.chain.append(e))

    def link_deployment(self, *, actor:str, deployment_id:str, now_ns:int)->"ProvenanceLedger":
        if deployment_id != self.state.manifest.deployment_id: raise ValueError("DEPLOYMENT_ID_MISMATCH")
        if not (self.state.approval_valid and self.state.evidence_valid and self.state.config_verified): raise ValueError("PROVENANCE_PREREQUISITES_MISSING")
        e=self._event(ProvenanceEventType.DEPLOYMENT_LINKED,actor,deployment_id,"DEPLOYMENT_BOUND_TO_RELEASE",now_ns)
        return ProvenanceLedger(ProvenanceState(self.state.manifest,self.state.approval_valid,self.state.evidence_valid,self.state.config_verified,True,self.state.revoked),self.chain.append(e))

    def link_rollback(self, *, actor:str, rollback_id:str, now_ns:int)->"ProvenanceLedger":
        e=self._event(ProvenanceEventType.ROLLBACK_LINKED,actor,rollback_id,"ROLLBACK_BOUND_TO_RELEASE",now_ns)
        return ProvenanceLedger(self.state,self.chain.append(e))

    def revoke(self, *, actor:str, reason:str, now_ns:int)->"ProvenanceLedger":
        if not reason: raise ValueError("REVOCATION_REASON_REQUIRED")
        e=self._event(ProvenanceEventType.RELEASE_REVOKED,actor,self.state.manifest.release_id,reason,now_ns)
        s=ProvenanceState(self.state.manifest,self.state.approval_valid,self.state.evidence_valid,self.state.config_verified,self.state.deployment_linked,True)
        return ProvenanceLedger(s,self.chain.append(e))

    def audit(self)->None:
        self.chain.verify()
        refs=[e.reference_id for e in self.chain.events]
        if self.state.revoked and not any(e.event_type is ProvenanceEventType.RELEASE_REVOKED for e in self.chain.events): raise ValueError("REVOCATION_NOT_AUDITED")
        if self.state.deployment_linked and self.state.manifest.deployment_id not in refs: raise ValueError("DEPLOYMENT_LINK_NOT_AUDITED")


def verify_manifest(manifest:ReleaseManifest, *, expected_artifact:str, expected_code:str, expected_config:str)->bool:
    if any(not v for v in (manifest.release_id,manifest.artifact_sha256,manifest.code_sha256,manifest.config_sha256,manifest.approval_id,manifest.deployment_id)): return False
    if manifest.artifact_sha256 != expected_artifact or manifest.code_sha256 != expected_code or manifest.config_sha256 != expected_config: return False
    if not manifest.evidence_ids or len(set(manifest.evidence_ids)) != len(manifest.evidence_ids): return False
    return True

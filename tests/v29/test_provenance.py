from decimal import Decimal
import pytest
from trading_platform.v29.provenance import *

def manifest():
    return ReleaseManifest('R29','a'*64,'b'*64,'c'*64,('E1','E2'),'A1','D1',1)

def ledger():
    return ProvenanceLedger(ProvenanceState(manifest(),False,False,False,False))

def test_manifest_fingerprint_and_verification():
    m=manifest(); assert len(m.fingerprint)==64
    assert verify_manifest(m,expected_artifact='a'*64,expected_code='b'*64,expected_config='c'*64)
    assert not verify_manifest(m,expected_artifact='d'*64,expected_code='b'*64,expected_config='c'*64)

def test_full_provenance_becomes_deployable():
    x=ledger().attach_approval(actor='op',valid=True,approval_id='A1',now_ns=2)
    x=x.attach_evidence(actor='op',evidence_ids=['E2','E1'],now_ns=3)
    x=x.verify_config(actor='op',observed_sha256='c'*64,now_ns=4)
    assert not x.state.deployable
    x=x.link_deployment(actor='op',deployment_id='D1',now_ns=5)
    assert x.state.deployable; x.audit()

def test_wrong_approval_and_config_fail():
    with pytest.raises(ValueError,match='APPROVAL_ID_MISMATCH'): ledger().attach_approval(actor='op',valid=True,approval_id='BAD',now_ns=2)
    with pytest.raises(ValueError,match='CONFIG_FINGERPRINT_MISMATCH'): ledger().verify_config(actor='op',observed_sha256='d'*64,now_ns=2)

def test_release_revocation_is_fail_closed_and_audited():
    x=ledger().revoke(actor='security',reason='evidence invalidated',now_ns=9)
    assert x.state.revoked and not x.state.deployable
    x.audit()

def test_deployment_requires_all_prerequisites():
    with pytest.raises(ValueError,match='PROVENANCE_PREREQUISITES_MISSING'): ledger().link_deployment(actor='op',deployment_id='D1',now_ns=1)

def test_chain_tamper_detected():
    x=ledger().attach_approval(actor='op',valid=True,approval_id='A1',now_ns=2)
    e=x.chain.events[0]
    bad=ProvenanceEvent(e.sequence,e.event_type,e.release_id,e.actor,e.reference_id,'tampered',e.timestamp_ns,e.previous_hash,e.event_hash)
    with pytest.raises(ValueError,match='PROVENANCE_CHAIN_INVALID'): ProvenanceChain((bad,)).verify()

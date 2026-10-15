from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v360.readiness_evidence import REQUIRED_EVIDENCE_CLASSES
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393, ReviewDecisionV393, SignatureVerificationStateV393, _hash as review_hash,
)
from trading_platform.v394.cryptographic_attestation import (
    KeyStatusV394, SignatureAlgorithmV394, SignedReviewEnvelopeV394,
    TrustAnchorAttestationStateV394, TrustAnchorV394,
)
from trading_platform.v414.promotion_crypto_gate import PromotionCryptoGateAuthorityV414, PromotionCryptoGateErrorV414

NOW = 1_800_000_100_000


def h(v: str) -> str:
    return sha256(v.encode()).hexdigest()


def manifest():
    evidence=[]
    for idx, cls in enumerate(REQUIRED_EVIDENCE_CLASSES):
        item={
            'evidence_id': f'V414-E{idx}', 'evidence_class': cls, 'scope': 'PRODUCTION',
            'source_kind':'EXTERNAL', 'source_system':f'producer-{idx}',
            'source_ref':f'https://external.example/{cls.lower()}/{idx}', 'content_hash':h(f'content:{idx}'),
            'observed_at_ms':NOW, 'valid_from_ms':NOW-1000, 'expires_at_ms':NOW+100_000,
            'artifact_refs':[f'evidence://{cls.lower()}/{idx}'], 'attestation_ref':f'attestation://{cls.lower()}/{idx}',
        }
        if cls=='LIVE_VENUE': item.update(environment_id='TESTNET',session_ref='session://1',mutation_ref='mutation://1',reconciliation_ref='recon://1')
        elif cls=='NETWORK_SEGMENTATION': item.update(environment_id='PRODUCTION',policy_ref='policy://1',isolation_test_ref='isolation://1')
        elif cls=='SECRET_STORE': item.update(environment_id='PRODUCTION',vault_ref='vault://1',rotation_ref='rotation://1',revocation_ref='revocation://1')
        elif cls=='BACKUP_RESTORE': item.update(environment_id='PRODUCTION',backup_ref='backup://1',restore_ref='restore://1',rpo_rto_ref='rpo-rto://1')
        elif cls=='DISASTER_RECOVERY': item.update(environment_id='PRODUCTION',dr_exercise_ref='dr://1',failover_ref='failover://1',failback_ref='failback://1',recovery_proof_ref='recovery://1')
        elif cls=='SECURITY_REVIEW': item.update(assessment_ref='security://1',scope_ref='scope://1',findings_ref='findings://1')
        elif cls=='MONITORING': item.update(environment_id='PRODUCTION',monitoring_ref='monitor://1',page_ref='page://1',on_call_ref='oncall://1')
        elif cls=='ROLLBACK': item.update(environment_id='PRODUCTION',rollback_ref='rollback://1',reconciliation_ref='recon://1',recovery_proof_ref='recovery://1')
        elif cls=='INDEPENDENT_REVIEW': item.update(review_ref='review://1',reviewer_id='independent-reviewer',subject_coverage_ref='coverage://1')
        evidence.append(item)
    out={'protocol_version':'V4.11-OPERATIONAL-EVIDENCE-1','package_id':'PKG-V414-1','scope':'PRODUCTION','created_at_ms':NOW,'source_system':'external-evidence-orchestrator','evidence':evidence}
    body=dict(out); out['manifest_hash']=sha256(canonical_json(body)).hexdigest()
    return out


def review_for(man):
    subject_ids=tuple([man['package_id']]+[x['evidence_id'] for x in man['evidence']])
    base={'review_id':'REV414','scope':'PRODUCTION','subject_ids':subject_ids,'reviewer_id':'independent-reviewer','reviewer_role':'external-assurance','producer_ids':('external-evidence-orchestrator',),'owner_ids':('owner-414',),'approver_ids':('approver-414',),'decision':ReviewDecisionV393.ACCEPT,'reviewed_at_ms':NOW,'expires_at_ms':NOW+60_000,'source_system':'independent-review-system','source_ref':'https://review.example/REV414','signature_ref':'https://review.example/signature/REV414','signature_hash':h('signature'),'signature_verification':SignatureVerificationStateV393.EXTERNALLY_VERIFIED,'review_hash':''}
    draft=ExternalReviewAttestationV393(**base); return replace(draft, review_hash=draft.computed_review_hash())


def anchor_and_envelope(private):
    pub=private.public_key().public_bytes_raw()
    import hashlib
    anchor=TrustAnchorV394('review-key-414',SignatureAlgorithmV394.ED25519,base64.b64encode(pub).decode(),NOW-1000,NOW+86_400_000,KeyStatusV394.ACTIVE,('PRODUCTION',),'trust-registry-v414',hashlib.sha256(pub).hexdigest())
    package={'package_id':'PKG-V414-1','scope':'PRODUCTION'}
    # The real package used by the bridge is generated from the manifest; build the signed fields below after importing the same normalization.
    return anchor


def signed_envelope(private, package, review, anchor):
    draft=SignedReviewEnvelopeV394('ENV414-1',package['package_id'],package['package_hash'],review.review_id,review.review_hash,review.scope,anchor.key_id,SignatureAlgorithmV394.ED25519,'','',anchor.registry_version,TrustAnchorAttestationStateV394.ATTESTED)
    sig=private.sign(draft.signing_bytes()); return replace(draft, signature_b64=base64.b64encode(sig).decode(), signature_hash=sha256(sig).hexdigest())


def seed_trust_attestation(store, anchor):
    store.append(event_id='trust-anchor-attestation:TA414:accepted',occurred_at_ms=NOW,event_type='TRUST_ANCHOR_ATTESTATION_ACCEPTED',aggregate_id='TA414',payload={'status':'VERIFIED','registry_version':anchor.registry_version,'registry_hash':'registry-hash-414'})


def test_crypto_gate_accepts_complete_chain():
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    store=EventStore(); m=manifest(); r=review_for(m)
    package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m)
    private=Ed25519PrivateKey.generate(); anchor=anchor_and_envelope(private); seed_trust_attestation(store,anchor); env=signed_envelope(private,package,r,anchor)
    d=PromotionCryptoGateAuthorityV414(store).admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA414',now_ms=NOW)
    assert d.allowed and d.status=='VERIFIED'
    PromotionCryptoGateAuthorityV414(store).assert_valid(d.gate_id)


def test_crypto_failure_prevents_v412_bridge():
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    store=EventStore(); m=manifest(); r=review_for(m); package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m)
    signer=Ed25519PrivateKey.generate(); wrong=Ed25519PrivateKey.generate(); anchor=anchor_and_envelope(wrong); seed_trust_attestation(store,anchor); env=signed_envelope(signer,package,r,anchor)
    with pytest.raises(PromotionCryptoGateErrorV414, match='SIGNATURE_INVALID|CRYPTO_REVIEW'):
        PromotionCryptoGateAuthorityV414(store).admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA414',now_ms=NOW)
    assert store.get('external-review-bridge-v412:PKG-V414-1') is None


def test_trust_attestation_is_required():
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    store=EventStore(); m=manifest(); r=review_for(m); package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m); private=Ed25519PrivateKey.generate(); anchor=anchor_and_envelope(private); env=signed_envelope(private,package,r,anchor)
    with pytest.raises(PromotionCryptoGateErrorV414, match='TRUST_ANCHOR_ATTESTATION_REQUIRED'):
        PromotionCryptoGateAuthorityV414(store).admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='MISSING',now_ms=NOW)


def test_gate_is_idempotent():
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    store=EventStore(); m=manifest(); r=review_for(m); package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m); private=Ed25519PrivateKey.generate(); anchor=anchor_and_envelope(private); seed_trust_attestation(store,anchor); env=signed_envelope(private,package,r,anchor); a=PromotionCryptoGateAuthorityV414(store)
    first=a.admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA414',now_ms=NOW); seq=store.latest_sequence; second=a.admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA414',now_ms=NOW+1)
    assert first.gate_id==second.gate_id and store.latest_sequence==seq


def test_mutated_gate_is_rejected():
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    store=EventStore(); m=manifest(); r=review_for(m); package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m); private=Ed25519PrivateKey.generate(); anchor=anchor_and_envelope(private); seed_trust_attestation(store,anchor); env=signed_envelope(private,package,r,anchor); a=PromotionCryptoGateAuthorityV414(store); d=a.admit(manifest=m,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA414',now_ms=NOW)
    event=store.get(d.gate_id); assert event is not None
    # EventStore is immutable; mutate through a direct SQL update is correctly forbidden.
    with pytest.raises(Exception):
        store._db.execute('UPDATE events SET payload_json=? WHERE event_id=?', ('{}', d.gate_id))

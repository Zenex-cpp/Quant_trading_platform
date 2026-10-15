from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v393.external_review_authority import ExternalReviewAttestationV393, ReviewDecisionV393, SignatureVerificationStateV393
from trading_platform.v394.cryptographic_attestation import KeyStatusV394, SignatureAlgorithmV394, SignedReviewEnvelopeV394, TrustAnchorAttestationStateV394, TrustAnchorV394
from trading_platform.v413.crypto_review import PromotionCryptoReviewAuthorityV413, PromotionCryptoReviewErrorV413
from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
from tests.v414.test_promotion_crypto_gate import manifest, review_for

NOW=1_800_000_100_000


def fixture():
    store=EventStore(); m=manifest(); r=review_for(m); package=ExternalReviewBridgeAuthorityV412(store)._normalized_package(m)
    private=Ed25519PrivateKey.generate(); pub=private.public_key().public_bytes_raw(); fp=sha256(pub).hexdigest()
    anchor=TrustAnchorV394('review-key-413',SignatureAlgorithmV394.ED25519,base64.b64encode(pub).decode(),NOW-1000,NOW+86_400_000,KeyStatusV394.ACTIVE,('PRODUCTION',),'trust-registry-v413',fp)
    draft=SignedReviewEnvelopeV394('ENV413-1',package['package_id'],package['package_hash'],r.review_id,r.review_hash,r.scope,anchor.key_id,SignatureAlgorithmV394.ED25519,'','',anchor.registry_version,TrustAnchorAttestationStateV394.ATTESTED)
    sig=private.sign(draft.signing_bytes()); env=replace(draft,signature_b64=base64.b64encode(sig).decode(),signature_hash=sha256(sig).hexdigest())
    store.append(event_id='trust-anchor-attestation:TA413:accepted',occurred_at_ms=NOW,event_type='TRUST_ANCHOR_ATTESTATION_ACCEPTED',aggregate_id='TA413',payload={'status':'VERIFIED','registry_version':anchor.registry_version})
    return store,m,r,package,anchor,env


def test_verifies_crypto_predecessor():
    store,m,r,package,anchor,env=fixture(); d=PromotionCryptoReviewAuthorityV413(store).verify(package=package,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='TA413',now_ms=NOW)
    assert d.allowed and d.status=='VERIFIED'


def test_missing_trust_attestation_blocks():
    store,m,r,package,anchor,env=fixture()
    with pytest.raises(PromotionCryptoReviewErrorV413, match='TRUST_ANCHOR_ATTESTATION_REQUIRED'):
        PromotionCryptoReviewAuthorityV413(store).verify(package=package,review=r,envelope=env,trust_anchor=anchor,trust_anchor_attestation_id='MISSING',now_ms=NOW)


def test_signature_tamper_blocks():
    store,m,r,package,anchor,env=fixture(); bad=replace(env,package_hash='0'*64)
    with pytest.raises(PromotionCryptoReviewErrorV413, match='CRYPTO_VERIFICATION:SIGNED_HASH_BINDING_MISMATCH'):
        PromotionCryptoReviewAuthorityV413(store).verify(package=package,review=r,envelope=bad,trust_anchor=anchor,trust_anchor_attestation_id='TA413',now_ms=NOW)

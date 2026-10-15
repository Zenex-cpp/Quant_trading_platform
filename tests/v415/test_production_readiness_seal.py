from __future__ import annotations

import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v415.production_readiness_seal import ProductionReadinessSealAuthorityV415, ProductionReadinessSealErrorV415
from trading_platform.v414.promotion_crypto_gate import PromotionCryptoGateAuthorityV414


def _crypto_gate():
    from tests.v414.test_promotion_crypto_gate import anchor_and_envelope, manifest, review_for, seed_trust_attestation, signed_envelope
    from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    store = EventStore(); m = manifest(); r = review_for(m)
    package = ExternalReviewBridgeAuthorityV412(store)._normalized_package(m)
    private = Ed25519PrivateKey.generate(); anchor = anchor_and_envelope(private); seed_trust_attestation(store, anchor)
    env = signed_envelope(private, package, r, anchor)
    decision = PromotionCryptoGateAuthorityV414(store).admit(manifest=m, review=r, envelope=env, trust_anchor=anchor, trust_anchor_attestation_id='TA414', now_ms=1_800_000_100_000)
    return store, decision


def test_complete_readiness_seal_is_durable_and_has_no_runtime_flag():
    store, gate = _crypto_gate()
    store.append(
        event_id='critical-promotion-readiness:DEC-415:accepted',
        occurred_at_ms=200,
        event_type='CRITICAL_PROMOTION_READINESS_ACCEPTED',
        aggregate_id='BUNDLE-415',
        payload={'status':'VERIFIED','bundle_id':'BUNDLE-415'},
    )
    authority = ProductionReadinessSealAuthorityV415(store)
    decision = authority.seal(seal_id='SEAL-415', bundle_id='BUNDLE-415', crypto_gate_id=gate.gate_id, critical_readiness_id='DEC-415')
    assert decision.allowed and decision.status == 'VERIFIED'
    assert authority.get('SEAL-415') is not None
    assert not hasattr(authority, 'production_ready')
    authority.assert_valid('SEAL-415')


def test_bundle_binding_mismatch_blocks_final_seal():
    store, gate = _crypto_gate()
    store.append(
        event_id='critical-promotion-readiness:DEC-415-B:accepted',
        occurred_at_ms=200,
        event_type='CRITICAL_PROMOTION_READINESS_ACCEPTED',
        aggregate_id='BUNDLE-A',
        payload={'status':'VERIFIED','bundle_id':'BUNDLE-A'},
    )
    with pytest.raises(ProductionReadinessSealErrorV415, match='CRITICAL_READINESS_BUNDLE_MISMATCH'):
        ProductionReadinessSealAuthorityV415(store).seal(seal_id='SEAL-415-B', bundle_id='BUNDLE-B', crypto_gate_id=gate.gate_id, critical_readiness_id='DEC-415-B')


def test_missing_critical_readiness_blocks_after_crypto_gate():
    store, gate = _crypto_gate()
    with pytest.raises(ProductionReadinessSealErrorV415, match='CRITICAL_PROMOTION_READINESS_REQUIRED'):
        ProductionReadinessSealAuthorityV415(store).seal(seal_id='SEAL-415-C', bundle_id='BUNDLE-C', crypto_gate_id=gate.gate_id, critical_readiness_id='MISSING')

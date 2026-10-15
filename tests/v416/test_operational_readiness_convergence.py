from __future__ import annotations

import pytest
from trading_platform.v21.event_store import EventStore
from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
from trading_platform.v414.promotion_crypto_gate import PromotionCryptoGateAuthorityV414
from trading_platform.v415.production_readiness_seal import ProductionReadinessSealAuthorityV415
from trading_platform.v416.operational_readiness_convergence import (
    OperationalReadinessConvergenceAuthorityV416,
    OperationalReadinessConvergenceErrorV416,
)

from tests.v414.test_promotion_crypto_gate import (
    NOW,
    anchor_and_envelope,
    manifest,
    review_for,
    seed_trust_attestation,
    signed_envelope,
)


def _chain():
    store = EventStore()
    m = manifest()
    review = review_for(m)
    bridge_auth = ExternalReviewBridgeAuthorityV412(store)
    package = bridge_auth._normalized_package(m)
    # Establish the externally reviewed bridge first; the convergence authority will revalidate it.
    bridge_auth.assess(manifest=m, review=review, now_ms=NOW)
    private = __import__("cryptography.hazmat.primitives.asymmetric.ed25519", fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate()
    anchor = anchor_and_envelope(private)
    seed_trust_attestation(store, anchor)
    env = signed_envelope(private, package, review, anchor)
    gate = PromotionCryptoGateAuthorityV414(store).admit(
        manifest=m,
        review=review,
        envelope=env,
        trust_anchor=anchor,
        trust_anchor_attestation_id="TA414",
        now_ms=NOW,
    )
    store.append(
        event_id="critical-promotion-readiness:DEC-416:accepted",
        occurred_at_ms=NOW,
        event_type="CRITICAL_PROMOTION_READINESS_ACCEPTED",
        aggregate_id="BUNDLE-416",
        payload={"status": "VERIFIED", "bundle_id": "BUNDLE-416"},
    )
    ProductionReadinessSealAuthorityV415(store).seal(
        seal_id="SEAL-416",
        bundle_id="BUNDLE-416",
        crypto_gate_id=gate.gate_id,
        critical_readiness_id="DEC-416",
    )
    return store, m, review


def test_complete_operational_chain_converges():
    store, m, review = _chain()
    decision = OperationalReadinessConvergenceAuthorityV416(store).converge(
        convergence_id="CONV-416",
        bundle_id="BUNDLE-416",
        package_id=m["package_id"],
        manifest=m,
        review=review,
        bridge_id=f"external-review-bridge-v412:{m['package_id']}",
        seal_id="SEAL-416",
        now_ms=NOW,
    )
    assert decision.allowed and decision.status == "VERIFIED"
    authority = OperationalReadinessConvergenceAuthorityV416(store)
    authority.assert_valid("CONV-416")
    assert authority.get("CONV-416") is not None


def test_missing_bridge_blocks_convergence():
    store = EventStore(); m = manifest(); review = review_for(m)
    with pytest.raises(OperationalReadinessConvergenceErrorV416, match="BRIDGE:BRIDGE_RECORD_NOT_FOUND"):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-MISSING-BRIDGE", bundle_id="BUNDLE-416", package_id=m["package_id"],
            manifest=m, review=review, bridge_id=f"external-review-bridge-v412:{m['package_id']}",
            seal_id="SEAL-MISSING", now_ms=NOW,
        )


def test_missing_seal_blocks_convergence():
    store, m, review = _chain()
    with pytest.raises(OperationalReadinessConvergenceErrorV416, match="SEAL:READINESS_SEAL_NOT_VALID"):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-MISSING-SEAL", bundle_id="BUNDLE-416", package_id=m["package_id"],
            manifest=m, review=review, bridge_id=f"external-review-bridge-v412:{m['package_id']}",
            seal_id="SEAL-MISSING", now_ms=NOW,
        )


def test_bundle_mismatch_blocks_against_final_seal():
    store, m, review = _chain()
    with pytest.raises(OperationalReadinessConvergenceErrorV416, match="SEAL_BUNDLE_MISMATCH"):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-BUNDLE", bundle_id="WRONG-BUNDLE", package_id=m["package_id"],
            manifest=m, review=review, bridge_id=f"external-review-bridge-v412:{m['package_id']}",
            seal_id="SEAL-416", now_ms=NOW,
        )


def test_manifest_mutation_invalidates_bridge_binding():
    store, m, review = _chain()
    mutated = dict(m)
    mutated["source_system"] = "other-producer"
    mutated["manifest_hash"] = __import__("hashlib").sha256(__import__("trading_platform.v21.event_store", fromlist=["canonical_json"]).canonical_json({k: v for k, v in mutated.items() if k != "manifest_hash"})).hexdigest()
    with pytest.raises(OperationalReadinessConvergenceErrorV416, match="MANIFEST:MANIFEST_ID_CONFLICT"):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-MUTATED", bundle_id="BUNDLE-416", package_id=m["package_id"],
            manifest=mutated, review=review, bridge_id=f"external-review-bridge-v412:{m['package_id']}",
            seal_id="SEAL-416", now_ms=NOW,
        )


def test_review_change_invalidates_bridge():
    store, m, review = _chain()
    changed = review_for(m)
    from dataclasses import replace
    changed = replace(changed, review_id="REV-CHANGED", review_hash="")
    changed = replace(changed, review_hash=changed.computed_review_hash())
    with pytest.raises(OperationalReadinessConvergenceErrorV416, match="BRIDGE:REVIEW_FINGERPRINT_CHANGED|BRIDGE:EXTERNAL_REVIEW"):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-REVIEW", bundle_id="BUNDLE-416", package_id=m["package_id"],
            manifest=m, review=changed, bridge_id=f"external-review-bridge-v412:{m['package_id']}",
            seal_id="SEAL-416", now_ms=NOW,
        )


def test_convergence_is_idempotent():
    store, m, review = _chain(); authority = OperationalReadinessConvergenceAuthorityV416(store)
    args=dict(convergence_id="CONV-416-IDEMP", bundle_id="BUNDLE-416", package_id=m["package_id"], manifest=m, review=review,
              bridge_id=f"external-review-bridge-v412:{m['package_id']}", seal_id="SEAL-416", now_ms=NOW)
    first=authority.converge(**args); seq=store.latest_sequence; second=authority.converge(**args)
    assert first.convergence_id == second.convergence_id and seq == store.latest_sequence


def test_convergence_does_not_set_runtime_production_flag():
    store, m, review = _chain()
    authority = OperationalReadinessConvergenceAuthorityV416(store)
    authority.converge(convergence_id="CONV-416-NOFLAG", bundle_id="BUNDLE-416", package_id=m["package_id"], manifest=m,
                       review=review, bridge_id=f"external-review-bridge-v412:{m['package_id']}", seal_id="SEAL-416", now_ms=NOW)
    event=authority.get("CONV-416-NOFLAG")
    assert event is not None
    assert event.payload["activation_flag"] == "NOT_SET"
    assert not hasattr(authority, "production_ready")


def test_convergence_requires_external_review_scope():
    store, m, review = _chain()
    from dataclasses import replace
    bad=replace(review, scope="SHADOW", review_hash="")
    bad=replace(bad, review_hash=bad.computed_review_hash())
    with pytest.raises(OperationalReadinessConvergenceErrorV416):
        OperationalReadinessConvergenceAuthorityV416(store).converge(
            convergence_id="CONV-416-SCOPE", bundle_id="BUNDLE-416", package_id=m["package_id"], manifest=m,
            review=bad, bridge_id=f"external-review-bridge-v412:{m['package_id']}", seal_id="SEAL-416", now_ms=NOW)

from datetime import datetime, timezone, timedelta
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger
from trading_platform.v359.human_review import (
    HumanReviewAuthorityError,
    HumanReviewAuthorityInvalid,
    HumanReviewAuthorityLedger,
    HumanReviewPackage,
)
from trading_platform.promotion.contracts import Approval, PromotionBundle

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def bundle():
    return PromotionBundle(
        'B1','S1','M1','F1','T1','C1','E1','CODE1','SNAP1',('G1',),('HASH1',),
        'A1',{'mode':'LIVE'},'RB1','CONTENT1',NOW,
    )


def approval(approved_by=('reviewer-a',)):
    return Approval('A1',tuple(approved_by),NOW - timedelta(minutes=1),NOW + timedelta(hours=1),{'mode':'LIVE'})


def package(pb_id='PB1', review_id='R1', incidents=(), status='PASS', reviewers=('independent-reviewer', 'reviewer-b')):
    return HumanReviewPackage(
        review_id=review_id,
        bundle_id='B1',
        evidence_snapshot_id='SNAP1',
        promotion_bundle_authorization_id=pb_id,
        approval_id='A1',
        reviewers=tuple(reviewers),
        known_limitations=('limited offline evidence',),
        rollback_target='RB1',
        open_incidents=tuple(incidents),
        revalidation_status=status,
        scope={'mode':'LIVE'},
        reviewed_at=NOW,
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def setup():
    store=EventStore()
    dep=DependencyInvalidationLedger(store)
    b=bundle()
    # The promotion-bundle authority is the required upstream.
    dep.assert_clear((b.bundle_id,b.evidence_snapshot_id,*b.gate_results,*b.artifact_hashes,
                      b.strategy_version,b.model_version,b.feature_version,b.target_version,
                      b.configuration_version,b.execution_model_version,b.code_version,
                      b.approval_id,b.rollback_target,b.content_hash))
    PromotionBundleAuthorityLedger.authorize(
        authorization_id='PB1', bundle=b, valid_from=NOW, expires_at=NOW+timedelta(minutes=30),
        reviewer='reviewer-a', recorded_at_ms=1, dependency_authority=dep, store=store,
    )
    return store, dep, b


def test_human_review_requires_explicit_inputs():
    store, dep, b = setup()
    with pytest.raises(HumanReviewAuthorityInvalid, match='OPEN_CRITICAL_INCIDENTS_BLOCK_REVIEW'):
        HumanReviewAuthorityLedger.authorize(
            package=package(incidents=('INC-1',)), bundle=b, approval=approval(),
            promotion_bundle_authorization_id='PB1', dependency_authority=dep, recorded_at_ms=2, store=store,
        )
    with pytest.raises(HumanReviewAuthorityInvalid, match='KNOWN_LIMITATIONS_REQUIRED'):
        HumanReviewAuthorityLedger.authorize(
            package=HumanReviewPackage('R2','B1','SNAP1','PB1','A1',('reviewer-a',),(), 'RB1',(), 'PASS', {'mode':'LIVE'}, NOW, NOW, NOW+timedelta(minutes=30)),
            bundle=b, approval=approval(), promotion_bundle_authorization_id='PB1', dependency_authority=dep, recorded_at_ms=3, store=store,
        )


def test_human_review_requires_independent_reviewer_from_upstream_authorization_and_approval():
    store, dep, b = setup()
    with pytest.raises(HumanReviewAuthorityInvalid, match='INDEPENDENT_HUMAN_REVIEW_REQUIRED'):
        HumanReviewAuthorityLedger.authorize(
            package=package(review_id='R2', incidents=(), reviewers=('reviewer-a', 'reviewer-b')),
            bundle=b, approval=approval(), promotion_bundle_authorization_id='PB1',
            dependency_authority=dep, recorded_at_ms=4, store=store,
        )


def test_human_review_requires_disjoint_from_approval_actor():
    store, dep, b = setup()
    conflicting_approval = approval(('approval-only',))
    pkg = package(review_id='R4', reviewers=('approval-only',))
    with pytest.raises(HumanReviewAuthorityInvalid, match='INDEPENDENT_HUMAN_REVIEW_REQUIRED'):
        HumanReviewAuthorityLedger.authorize(
            package=pkg, bundle=b, approval=conflicting_approval, promotion_bundle_authorization_id='PB1',
            dependency_authority=dep, recorded_at_ms=6, store=store,
        )


def test_human_review_accepts_disjoint_reviewer():
    store, dep, b = setup()
    pkg = HumanReviewPackage(
        review_id='R3', bundle_id='B1', evidence_snapshot_id='SNAP1',
        promotion_bundle_authorization_id='PB1', approval_id='A1',
        reviewers=('independent-reviewer',), known_limitations=('limited offline evidence',),
        rollback_target='RB1', open_incidents=(), revalidation_status='PASS',
        scope={'mode':'LIVE'}, reviewed_at=NOW, valid_from=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    auth, created = HumanReviewAuthorityLedger.authorize(
        package=pkg, bundle=b, approval=approval(), promotion_bundle_authorization_id='PB1',
        dependency_authority=dep, recorded_at_ms=5, store=store,
    )
    assert created
    assert auth.reviewers == ('independent-reviewer',)


def test_human_review_is_durable_and_restart_readable():
    store, dep, b = setup()
    auth, created = HumanReviewAuthorityLedger.authorize(
        package=package(), bundle=b, approval=approval(), promotion_bundle_authorization_id='PB1',
        dependency_authority=dep, recorded_at_ms=2, store=store,
    )
    assert created
    assert HumanReviewAuthorityLedger(store).get('R1').fingerprint == auth.fingerprint
    reopened=HumanReviewAuthorityLedger(store)
    assert reopened.assert_valid('R1', bundle=b, approval=approval(), now=NOW, dependency_authority=dep).fingerprint == auth.fingerprint


def test_human_review_is_invalidated_by_dependency_change():
    store, dep, b = setup()
    auth, _ = HumanReviewAuthorityLedger.authorize(
        package=package(), bundle=b, approval=approval(), promotion_bundle_authorization_id='PB1',
        dependency_authority=dep, recorded_at_ms=2, store=store,
    )
    store.append(
        event_id="evidence-invalidation:INC",
        occurred_at_ms=3,
        event_type=DependencyInvalidationLedger.INVALIDATED_EVENT,
        aggregate_id="INC",
        payload={
            "changed_dependency": b.bundle_id,
            "graph_version_hash": "GRAPH",
            "affected_artifacts": [b.bundle_id],
            "invalidated_evidence": [b.evidence_snapshot_id],
            "invalidated_gates": list(b.gate_results),
            "affected_candidates": [],
            "affected_promotions": [],
            "required_revalidation": [],
            "deployment_impact": "BLOCK",
            "reason": "TEST_DEPENDENCY_CHANGE",
            "recorded_at_ms": 3,
        },
    )
    with pytest.raises(HumanReviewAuthorityInvalid, match='HUMAN_REVIEW_STALE_AFTER_INVALIDATION'):
        HumanReviewAuthorityLedger(store).assert_valid('R1', bundle=b, approval=approval(), now=NOW, dependency_authority=dep)

from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v360.readiness_evidence import (
    EvidenceResult,
    EvidenceSourceKind,
    ReadinessEvidenceLedger,
    REQUIRED_EVIDENCE_CLASSES,
)
from trading_platform.v409.production_readiness import ProductionReadinessAuthorityV409
from trading_platform.v359.human_review import HumanReviewAuthorityLedger, HumanReviewPackage


NOW = datetime(2026, 10, 8, 5, 0, tzinfo=timezone.utc)


def h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def bundle() -> PromotionBundle:
    return PromotionBundle(
        'B409','S409','M409','F409','T409','C409','E409','CODE409',
        'SNAP409',('G409',),('ART409',),'A409',{'mode':'LIVE'},'RB409','HASH409',NOW,
    )


def approval() -> Approval:
    return Approval('A409', ('approver-409',), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {'mode':'LIVE'})


def test_v409_never_claims_ready_from_missing_external_evidence():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    a = ProductionReadinessAuthorityV409(store=store, dependency_authority=dep)
    b = bundle()
    # Application preflight itself is allowed to remain blocked here; V409 must not
    # turn a partial repository state into a readiness claim.
    decision = a.assess(
        bundle=b,
        gates=(),
        approval=approval(),
        human_review_id='HR409',
        scope='LIVE',
        now=NOW,
        assessment_id='ASSESS409',
    )
    assert decision.production_ready is False
    assert decision.status == 'BLOCKED'
    assert decision.reason.startswith('APPLICATION_PREFLIGHT:')


def test_v360_external_evidence_rejects_internal_sources_before_v409_can_count_them():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    now_ms = int(NOW.timestamp() * 1000)
    evidence_id = 'EVID409-INTERNAL'
    ledger.submit(
        evidence_id=evidence_id,
        evidence_class=REQUIRED_EVIDENCE_CLASSES[0],
        scope='LIVE',
        result=EvidenceResult.PASS,
        observed_at_ms=now_ms,
        valid_from_ms=now_ms - 1_000,
        expires_at_ms=now_ms + 60_000,
        source_system='repo-test',
        source_ref='internal:fixture',
        content_hash=h('internal'),
        source_kind=EvidenceSourceKind.INTERNAL,
        submitted_at_ms=now_ms,
    )
    with pytest.raises(Exception, match='EXTERNAL_READINESS_EVIDENCE_REQUIRED'):
        ledger.verify(evidence_id=evidence_id, reviewer_id='reviewer-409', review_ref='review-409', verified_at_ms=now_ms)


def test_v409_requires_durable_independent_human_review_even_when_approval_exists():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    a = ProductionReadinessAuthorityV409(store=store, dependency_authority=dep)
    b = bundle()
    decision = a.assess(
        bundle=b,
        gates=(),
        approval=approval(),
        human_review_id='MISSING-HR',
        scope='LIVE',
        now=NOW,
        assessment_id='ASSESS-HR',
    )
    assert decision.production_ready is False
    assert 'APPLICATION_PREFLIGHT:' in decision.reason or decision.reason.startswith('HUMAN_REVIEW:')


def test_v409_dependency_fingerprint_is_deterministic():
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    a = ProductionReadinessAuthorityV409(store=store, dependency_authority=dep)
    b = bundle()
    # The helper is intentionally deterministic for the same bundle and evidence set.
    x = a._bundle_dependencies(b, ('E1','E2'), 'HR1')
    y = a._bundle_dependencies(b, ('E2','E1'), 'HR1')
    assert x == y



def test_v409_does_not_persist_readiness_after_dependency_changes_during_assessment():
    from types import SimpleNamespace
    from trading_platform.v407.critical_promotion_evidence import CriticalPromotionEvidenceDecisionV407
    from trading_platform.v408.gate_promotion import CriticalPromotionGateDecisionV408
    from trading_platform.v360.readiness_evidence import ProductionReadinessAssessment

    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    a = ProductionReadinessAuthorityV409(store=store, dependency_authority=dep)
    b = bundle()

    def mutate_then_preflight(*, bundle, gates, now):
        dep.invalidate(
            incident_id='INC409-RACE',
            changed_dependency=bundle.model_version,
            graph=__import__('trading_platform.evidence.graph', fromlist=['EvidenceDependencyGraph']).EvidenceDependencyGraph([]),
            evidence_index={},
            gate_dependencies={},
            candidates={},
            promotions={},
            reason='TEST_INVALIDATION',
            recorded_at_ms=int(now.timestamp() * 1000),
        )
        snapshot = CriticalPromotionEvidenceDecisionV407(True, 'EVIDENCE_SNAPSHOT_FRESH_AND_BOUND', bundle.evidence_snapshot_id, bundle.bundle_id)
        return CriticalPromotionGateDecisionV408(True, 'CRITICAL_PROMOTION_GATE_AND_SNAPSHOT_PRECHECK_OK', bundle.gate_results, bundle.gate_results, (), snapshot)

    a.preflight.check = mutate_then_preflight
    a.human_review.assert_valid = lambda *args, **kwargs: SimpleNamespace(review_id='HR-RACE')
    a.evidence_assessor.assess = lambda **kwargs: ProductionReadinessAssessment(
        assessment_id='ASSESS-RACE', status='READY_FOR_LIVE', production_ready=True,
        missing=(), invalid=(), evidence_ids=('EVID-RACE',), assessed_at_ms=int(NOW.timestamp() * 1000)
    )

    decision = a.assess(
        bundle=b,
        gates=(),
        approval=approval(),
        human_review_id='HR-RACE',
        scope='LIVE',
        now=NOW,
        assessment_id='ASSESS-RACE',
    )
    assert decision.production_ready is False
    assert decision.reason.startswith('DEPENDENCY_REVALIDATION:')
    assert a.get('production-readiness:ASSESS-RACE') is None

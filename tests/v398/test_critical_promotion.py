from base64 import b64encode
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
from trading_platform.evidence.snapshot import build_snapshot
from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.v408.gate_promotion import GatePromotionAuthorizationLedgerV408
from trading_platform.v398.critical_promotion import CriticalPromotionReadinessAuthorityV398, ExternalRollbackAttestationV398

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def anchor(key_id: str, scope: str):
    private = Ed25519PrivateKey.generate()
    pub = private.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return private, ReviewerTrustAnchorV395(key_id, b64encode(pub).decode(), NOW_MS - 1000, NOW_MS + 7 * 24 * 3600 * 1000, ReviewerKeyStatusV395.ACTIVE, (scope,), sha256(pub).hexdigest())


def bundle():
    return PromotionBundle("B398", "S398", "M398", "F398", "T398", "C398", "E398", "CODE398", "SNAP398", ("G0", "G1"), ("H1", "H2"), "APP398", {"environment": "PRODUCTION", "criticality": "CRITICAL"}, "ROLLBACK398", "CONTENT398", NOW)


def signed_rollback(b, private, **overrides):
    body = {
        "attestation_id": "RB398", "scope": "PRODUCTION_CRITICAL", "bundle_id": b.bundle_id,
        "evidence_snapshot_id": b.evidence_snapshot_id, "rollback_target": b.rollback_target,
        "release_artifact_hash": b.content_hash, "rollback_evidence_ref": "https://review.example/rb/398",
        "recovery_proof_ref": "https://review.example/recovery/398", "rollback_executed_at_ms": NOW_MS - 60000,
        "residual_risk_zero": True, "trading_blocked_after_rollback": True,
        "reviewer_id": "rollback-reviewer", "reviewer_key_id": "rollback-key", "operator_id": "rollback-operator",
        "reviewed_at_ms": NOW_MS - 30000, "expires_at_ms": NOW_MS + 3600000, "decision": "ACCEPT",
    }
    body.update(overrides)
    sig = private.sign(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return ExternalRollbackAttestationV398(**body, signature_b64=b64encode(sig).decode(), signature_hash=sha256(sig).hexdigest())


def seed(store, b, human_reviewers=("independent-reviewer",)):
    dep = DependencyInvalidationLedger(store)
    PromotionBundleAuthorityLedger.authorize(authorization_id="PB398", bundle=b, valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(hours=1), reviewer="bundle-reviewer", recorded_at_ms=NOW_MS, dependency_authority=dep, store=store)
    store.append(event_id="trust-anchor-attestation:TA398:accepted", occurred_at_ms=NOW_MS, event_type="TRUST_ANCHOR_ATTESTATION_ACCEPTED", aggregate_id=b.bundle_id, payload={"status":"VERIFIED"})
    store.append(event_id="security-monitoring-readiness:READY398:accepted", occurred_at_ms=NOW_MS, event_type="SECURITY_MONITORING_READINESS_ACCEPTED", aggregate_id=b.bundle_id, payload={"status":"VERIFIED", "release_artifact_hash":b.content_hash})
    store.append(event_id="external-dr-attestation:DR398:accepted", occurred_at_ms=NOW_MS, event_type="EXTERNAL_DR_ATTESTATION_ACCEPTED", aggregate_id=b.bundle_id, payload={"status":"VERIFIED"})
    snapshot = build_snapshot(
        b.evidence_snapshot_id,
        ("EV398",),
        {"metric": "verified"},
        b.gate_results,
        (b.bundle_id, b.model_version, *b.artifact_hashes),
        (b.strategy_version, b.model_version, b.feature_version, b.target_version, b.configuration_version, b.execution_model_version, b.code_version),
        b.artifact_hashes,
        ("METHODOLOGY398",),
        (b.approval_id,),
        b.scope,
    )
    EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snapshot,
        promotion_id=b.bundle_id,
        bundle_id=b.bundle_id,
        model_version=b.model_version,
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        reviewer="snapshot-reviewer",
        recorded_at_ms=NOW_MS,
        dependency_authority=dep,
    )
    gate_ledger = GatePromotionAuthorizationLedgerV408(store)
    for gate_id in b.gate_results:
        gate_ledger.authorize(
            gate=Gate(
                gate_id, b.model_version, f"RUN-{gate_id}", (b.model_version,), (f"CHECK-{gate_id}",),
                GateResult.PASS, b.artifact_hashes, ("EV398",), "gate-owner", "gate-reviewer",
                NOW.isoformat(), None, "rerun_on_dependency_change",
            ),
            dependency_authority=dep, recorded_at_ms=NOW_MS,
        )
    store.append(event_id="human-review:approve:HR398", occurred_at_ms=NOW_MS, event_type="HUMAN_REVIEW_APPROVED", aggregate_id=b.bundle_id, payload={
        "review_id":"HR398", "bundle_id":b.bundle_id, "evidence_snapshot_id":b.evidence_snapshot_id, "promotion_bundle_authorization_id":"PB398", "approval_id":b.approval_id,
        "package_fingerprint":"FP398", "valid_from":(NOW - timedelta(minutes=1)).isoformat(), "expires_at":(NOW + timedelta(hours=1)).isoformat(),
        "reviewers":list(human_reviewers), "recorded_at_ms":NOW_MS, "dependency_checkpoint_sequence":0, "dependency_keys":[],
    })
    return dep


def admit(store, dep, b, approval, rb, anchor_obj, decision_id="DEC398"):
    return CriticalPromotionReadinessAuthorityV398(store).admit(
        decision_id=decision_id, bundle=b, approval=approval, promotion_bundle_authorization_id="PB398", human_review_id="HR398",
        readiness_id="READY398", dr_attestation_id="DR398", trust_anchor_attestation_id="TA398", rollback_attestation=rb,
        rollback_reviewer_anchor=anchor_obj, dependency_authority=dep, now=NOW, now_ms=NOW_MS,
    )


def test_accepts_complete_critical_promotion():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = admit(store, dep, b, approval, signed_rollback(b, private), anchor_obj)
    assert decision.allowed and decision.status == "VERIFIED"
    assert CriticalPromotionReadinessAuthorityV398(store).get("DEC398") is not None


def test_requires_dual_approval():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a",), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = admit(store, dep, b, approval, signed_rollback(b, private), anchor_obj, "DEC-DUAL")
    assert not decision.allowed and decision.reason == "DUAL_APPROVAL_REQUIRED"


def test_rejects_rollback_hash_mismatch():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = admit(store, dep, b, approval, signed_rollback(b, private, release_artifact_hash="BAD"), anchor_obj, "DEC-HASH")
    assert not decision.allowed and decision.reason == "ROLLBACK_RELEASE_HASH_MISMATCH"


def test_rejects_human_reviewer_approver_conflict():
    store, b = EventStore(), bundle(); dep = seed(store, b, human_reviewers=("approver-a",))
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = admit(store, dep, b, approval, signed_rollback(b, private), anchor_obj, "DEC-CONFLICT")
    assert not decision.allowed and decision.reason == "HUMAN_REVIEWER_APPROVER_CONFLICT"


def test_rejects_missing_dr_attestation():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = CriticalPromotionReadinessAuthorityV398(store).admit(
        decision_id="DEC-DR", bundle=b, approval=approval, promotion_bundle_authorization_id="PB398", human_review_id="HR398",
        readiness_id="READY398", dr_attestation_id="MISSING-DR", trust_anchor_attestation_id="TA398", rollback_attestation=signed_rollback(b, private),
        rollback_reviewer_anchor=anchor_obj, dependency_authority=dep, now=NOW, now_ms=NOW_MS,
    )
    assert not decision.allowed and decision.reason == "DR_ATTESTATION_REQUIRED"


def test_rejects_expired_rollback():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    rb = signed_rollback(b, private, reviewed_at_ms=NOW_MS - 100000, expires_at_ms=NOW_MS - 1)
    decision = admit(store, dep, b, approval, rb, anchor_obj, "DEC-EXP")
    assert not decision.allowed and decision.reason == "ROLLBACK_ATTESTATION_EXPIRED"


def test_replay_is_idempotent():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"PRODUCTION","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    rb = signed_rollback(b, private)
    authority = CriticalPromotionReadinessAuthorityV398(store)
    first = admit(store, dep, b, approval, rb, anchor_obj, "DEC-IDEMP")
    seq = store.latest_sequence
    second = admit(store, dep, b, approval, rb, anchor_obj, "DEC-IDEMP")
    assert first.allowed and second.allowed and store.latest_sequence == seq


def test_requires_production_critical_scope():
    store, b = EventStore(), bundle(); dep = seed(store, b)
    b2 = PromotionBundle(**{**b.__dict__, "scope": {"environment":"CANARY","criticality":"CRITICAL"}})
    approval = Approval("APP398", ("approver-a", "approver-b"), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"environment":"CANARY","criticality":"CRITICAL"})
    private, anchor_obj = anchor("rollback-key", "PRODUCTION_CRITICAL")
    decision = admit(store, dep, b2, approval, signed_rollback(b2, private), anchor_obj, "DEC-SCOPE")
    assert not decision.allowed and decision.reason == "PRODUCTION_SCOPE_REQUIRED"

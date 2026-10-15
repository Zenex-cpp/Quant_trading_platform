from __future__ import annotations

import base64
from hashlib import sha256
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph, EvidenceGraphNode, EvidenceState
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v403.revalidation import ExternalReadinessRevalidationAuthorityV403, ReadinessRevalidationWitnessV403
from trading_platform.v404.revocation import ExternalReadinessRevocationAuthorityV404, ReadinessRevocationV404
from trading_platform.v405.revocation_dependency import RevocationDependencyBridgeV405


def _anchor(private: Ed25519PrivateKey, key_id: str = "reviewer-v405") -> ReviewerTrustAnchorV395:
    raw = private.public_key().public_bytes_raw()
    return ReviewerTrustAnchorV395(
        reviewer_key_id=key_id,
        public_key_b64=base64.b64encode(raw).decode(),
        valid_from_ms=0,
        expires_at_ms=9_999_999_999_999,
        status=ReviewerKeyStatusV395.ACTIVE,
        allowed_scopes=("PRODUCTION_CRITICAL",),
        fingerprint=sha256(raw).hexdigest(),
    )


def _sign(private: Ed25519PrivateKey, payload: dict) -> tuple[str, str]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    signature = private.sign(canonical)
    return base64.b64encode(signature).decode(), sha256(signature).hexdigest()


def _fixture():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    e = store.append(
        event_id="readiness-event",
        occurred_at_ms=1000,
        event_type="READINESS_A",
        aggregate_id="bundle-1",
        payload={"status": "VERIFIED"},
    ).event
    witness_body = {
        "witness_id": "witness-1",
        "scope": "PRODUCTION_CRITICAL",
        "bundle_id": "bundle-1",
        "evidence_snapshot_id": "snapshot-1",
        "release_artifact_hash": "a" * 64,
        "checked_event_hashes": [["readiness-event", e.event_hash]],
        "review_evidence_ref": "audit://external/w1",
        "reviewer_id": "reviewer-1",
        "operator_id": "operator-1",
        "reviewer_key_id": "reviewer-v405",
        "checked_at_ms": 2000,
        "expires_at_ms": 5000,
        "decision": "ACCEPT",
    }
    sig_b64, sig_hash = _sign(private, witness_body)
    witness = ReadinessRevalidationWitnessV403(
        **{**witness_body, "checked_event_hashes": (("readiness-event", e.event_hash),), "signature_b64": sig_b64, "signature_hash": sig_hash}
    )
    ExternalReadinessRevalidationAuthorityV403(store).admit(
        witness=witness, reviewer_anchor=_anchor(private), now_ms=3000
    )
    accepted = store.get("external-readiness-revalidation:witness-1:accepted")

    rev_body = {
        "revocation_id": "rev-1",
        "scope": "PRODUCTION_CRITICAL",
        "witness_id": "witness-1",
        "witness_fingerprint": str(accepted.payload["witness_fingerprint"]),
        "bundle_id": "bundle-1",
        "evidence_snapshot_id": "snapshot-1",
        "release_artifact_hash": "a" * 64,
        "reason_code": "SECURITY_EVIDENCE_INVALIDATED",
        "reviewer_id": "reviewer-2",
        "operator_id": "operator-1",
        "reviewer_key_id": "reviewer-v405",
        "revoked_at_ms": 3200,
        "decision": "REVOKE",
    }
    sig_b64, sig_hash = _sign(private, rev_body)
    revocation = ReadinessRevocationV404(**{**rev_body, "signature_b64": sig_b64, "signature_hash": sig_hash})
    ExternalReadinessRevocationAuthorityV404(store).revoke(
        revocation=revocation, reviewer_anchor=_anchor(private), now_ms=3300
    )

    graph = EvidenceDependencyGraph(
        [
            EvidenceGraphNode("witness-1", "REVALIDATION_WITNESS", "1", ()),
            EvidenceGraphNode("snapshot-1", "EVIDENCE_SNAPSHOT", "1", ("witness-1",)),
            EvidenceGraphNode("bundle-1", "PROMOTION_BUNDLE", "1", ("snapshot-1",)),
            EvidenceGraphNode("promotion-1", "PROMOTION", "1", ("bundle-1",)),
        ]
    )
    evidence = {
        "snapshot-evidence": Evidence(
            "snapshot-evidence", "READINESS", EvidenceState.VALID, "1", "2026-10-07T00:00:00Z",
            (), ("snapshot-1",), "m1", {"environment": "PRODUCTION"}, (None, None), "b" * 64, "owner"
        )
    }
    gates = {"gate-1": ("bundle-1",)}
    candidates = {"candidate-1": ("gate-1",)}
    promotions = {"promotion-1": ("candidate-1",)}
    return store, private, revocation, graph, evidence, gates, candidates, promotions


def test_revocation_propagates_to_dependency_ledger():
    store, _, revocation, graph, evidence, gates, candidates, promotions = _fixture()
    bridge = RevocationDependencyBridgeV405(
        store=store, dependency_authority=DependencyInvalidationLedger(store)
    )
    decision = bridge.invalidate(
        revocation=revocation,
        graph=graph,
        evidence_index=evidence,
        gate_dependencies=gates,
        candidates=candidates,
        promotions=promotions,
        recorded_at_ms=3400,
        accepted_now_ms=3400,
    )
    assert decision.allowed
    assert decision.state == "ACTIVE"
    assert decision.invalidation is not None
    assert "promotion-1" in decision.invalidation.affected_promotions
    assert bridge.dependency_authority.blocked_dependencies(("promotion-1",)) == ("promotion-1",)
    assert store.verify_chain()


def test_revocation_dependency_is_idempotent():
    store, _, revocation, graph, evidence, gates, candidates, promotions = _fixture()
    ledger = DependencyInvalidationLedger(store)
    bridge = RevocationDependencyBridgeV405(store=store, dependency_authority=ledger)
    kwargs = dict(
        revocation=revocation, graph=graph, evidence_index=evidence, gate_dependencies=gates,
        candidates=candidates, promotions=promotions, recorded_at_ms=3400, accepted_now_ms=3400,
    )
    first = bridge.invalidate(**kwargs)
    second = bridge.invalidate(**kwargs)
    assert first.allowed and second.allowed
    assert first.invalidation == second.invalidation
    matches = [
        e for e in store.iter_events()
        if e.event_type == DependencyInvalidationLedger.INVALIDATED_EVENT
    ]
    assert len(matches) == 1


def test_revocation_requires_graph_root():
    store, _, revocation, _, evidence, gates, candidates, promotions = _fixture()
    ledger = DependencyInvalidationLedger(store)
    bridge = RevocationDependencyBridgeV405(store=store, dependency_authority=ledger)
    empty_graph = EvidenceDependencyGraph()
    decision = bridge.invalidate(
        revocation=revocation, graph=empty_graph, evidence_index=evidence,
        gate_dependencies=gates, candidates=candidates, promotions=promotions,
        recorded_at_ms=3400, accepted_now_ms=3400,
    )
    assert not decision.allowed
    assert decision.reason == "REVOCATION_WITNESS_NOT_IN_DEPENDENCY_GRAPH"
    assert ledger.active_incidents() == ()


def test_shared_event_store_is_required():
    store = EventStore()
    other = EventStore()
    try:
        RevocationDependencyBridgeV405(
            store=store,
            revocation_authority=ExternalReadinessRevocationAuthorityV404(other),
        )
    except ValueError as exc:
        assert str(exc) == "SHARED_EVENT_STORE_REQUIRED"
    else:
        raise AssertionError("expected shared-store rejection")


def test_revocation_must_be_durable_before_propagation():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    body = {
        "revocation_id": "rev-1", "scope": "PRODUCTION_CRITICAL", "witness_id": "missing",
        "witness_fingerprint": "a" * 64, "bundle_id": "bundle-1", "evidence_snapshot_id": "snapshot-1",
        "release_artifact_hash": "b" * 64, "reason_code": "X", "reviewer_id": "r",
        "operator_id": "o", "reviewer_key_id": "reviewer-v405", "revoked_at_ms": 1, "decision": "REVOKE",
    }
    sig_b64, sig_hash = _sign(private, body)
    revocation = ReadinessRevocationV404(**{**body, "signature_b64": sig_b64, "signature_hash": sig_hash})
    bridge = RevocationDependencyBridgeV405(store=store)
    decision = bridge.invalidate(
        revocation=revocation, graph=EvidenceDependencyGraph(), evidence_index={}, gate_dependencies={},
        candidates={}, promotions={}, recorded_at_ms=2, accepted_now_ms=2,
    )
    assert not decision.allowed
    assert decision.reason == "REVALIDATION_WITNESS_NOT_FOUND"

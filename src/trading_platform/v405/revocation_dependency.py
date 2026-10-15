from __future__ import annotations

from dataclasses import dataclass

from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationLedger,
    DependencyInvalidationRecord,
    DependencyInvalidationError,
)
from trading_platform.v404.revocation import (
    ExternalReadinessRevocationAuthorityV404,
    ReadinessRevocationV404,
    RevalidationStatusV404,
    RevocationErrorV404,
)


class RevocationDependencyErrorV405(ValueError):
    __test__ = False


@dataclass(frozen=True)
class RevocationDependencyDecisionV405:
    allowed: bool
    reason: str
    incident_id: str
    revocation_id: str
    witness_id: str
    state: str
    invalidation: DependencyInvalidationRecord | None


class RevocationDependencyBridgeV405:
    """Bind accepted witness revocation to the durable dependency-invalidation ledger.

    The bridge is deliberately fail-closed: it refuses to create an invalidation unless
    the revocation is already durably accepted and the witness is present as a graph node.
    The graph remains immutable; the ledger records the computed blast radius.
    """

    REASON = "EXTERNAL_READINESS_REVOCATION"

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        revocation_authority: ExternalReadinessRevocationAuthorityV404 | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.revocation_authority = revocation_authority or ExternalReadinessRevocationAuthorityV404(self.store)
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.revocation_authority.store is not self.store or self.dependency_authority.store is not self.store:
            raise RevocationDependencyErrorV405("SHARED_EVENT_STORE_REQUIRED")

    @staticmethod
    def _incident_id(revocation: ReadinessRevocationV404) -> str:
        return f"revalidation-revocation:{revocation.witness_id}:{revocation.revocation_id}"

    @staticmethod
    def _present_graph_root(graph: EvidenceDependencyGraph, witness_id: str) -> bool:
        return witness_id in graph.snapshot()

    def invalidate(
        self,
        *,
        revocation: ReadinessRevocationV404,
        graph: EvidenceDependencyGraph,
        evidence_index: dict[str, Evidence],
        gate_dependencies: dict[str, tuple[str, ...]],
        candidates: dict[str, tuple[str, ...]],
        promotions: dict[str, tuple[str, ...]],
        recorded_at_ms: int,
        accepted_now_ms: int,
    ) -> RevocationDependencyDecisionV405:
        incident_id = self._incident_id(revocation)
        try:
            if recorded_at_ms < 0 or accepted_now_ms < 0:
                raise RevocationDependencyErrorV405("INVALIDATION_TIMESTAMP_INVALID")
            if not self.store.verify_chain():
                raise RevocationDependencyErrorV405("EVENT_CHAIN_INVALID")

            witness_event = self.store.get(
                f"external-readiness-revalidation:{revocation.witness_id}:accepted"
            )
            if witness_event is None:
                raise RevocationDependencyErrorV405("REVALIDATION_WITNESS_NOT_FOUND")
            if self.store.get(
                f"external-readiness-revalidation:{revocation.witness_id}:revoked"
            ) is None:
                raise RevocationDependencyErrorV405("REVALIDATION_REVOCATION_NOT_DURABLE")

            status = self.revocation_authority.status(revocation.witness_id, now_ms=accepted_now_ms)
            if status is not RevalidationStatusV404.REVOKED:
                raise RevocationDependencyErrorV405("REVALIDATION_REVOCATION_STATUS_INVALID")

            if str(witness_event.payload.get("witness_fingerprint")) != revocation.witness_fingerprint:
                raise RevocationDependencyErrorV405("REVOCATION_WITNESS_FINGERPRINT_MISMATCH")
            if str(witness_event.payload.get("bundle_id")) != revocation.bundle_id:
                raise RevocationDependencyErrorV405("REVOCATION_BUNDLE_MISMATCH")
            if str(witness_event.payload.get("evidence_snapshot_id")) != revocation.evidence_snapshot_id:
                raise RevocationDependencyErrorV405("REVOCATION_SNAPSHOT_MISMATCH")
            if str(witness_event.payload.get("release_artifact_hash")) != revocation.release_artifact_hash:
                raise RevocationDependencyErrorV405("REVOCATION_RELEASE_HASH_MISMATCH")

            if not self._present_graph_root(graph, revocation.witness_id):
                raise RevocationDependencyErrorV405("REVOCATION_WITNESS_NOT_IN_DEPENDENCY_GRAPH")

            record, _ = self.dependency_authority.invalidate(
                incident_id=incident_id,
                changed_dependency=revocation.witness_id,
                graph=graph,
                evidence_index=evidence_index,
                gate_dependencies=gate_dependencies,
                candidates=candidates,
                promotions=promotions,
                reason=self.REASON,
                recorded_at_ms=recorded_at_ms,
            )
            if not self.store.verify_chain():
                raise RevocationDependencyErrorV405("EVENT_CHAIN_INVALID_AFTER_INVALIDATION")
            return RevocationDependencyDecisionV405(
                True,
                "EXTERNAL_READINESS_REVOCATION_PROPAGATED",
                incident_id,
                revocation.revocation_id,
                revocation.witness_id,
                record.state.value,
                record,
            )
        except (RevocationDependencyErrorV405, RevocationErrorV404, DependencyInvalidationError) as exc:
            return RevocationDependencyDecisionV405(
                False,
                str(exc),
                incident_id,
                revocation.revocation_id,
                revocation.witness_id,
                "REJECTED",
                None,
            )

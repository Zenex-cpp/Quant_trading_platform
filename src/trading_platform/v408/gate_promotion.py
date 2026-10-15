from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationError,
    DependencyInvalidationLedger,
)
from trading_platform.v407.critical_promotion_evidence import (
    CriticalPromotionEvidenceDecisionV407,
    CriticalPromotionEvidencePreflightV407,
)


class CriticalPromotionGateErrorV408(ValueError):
    __test__ = False


@dataclass(frozen=True)
class GatePromotionAuthorizationV408:
    authorization_id: str
    gate_id: str
    run_id: str
    candidate_version: str
    dependency_checkpoint: int
    gate_fingerprint: str
    recorded_at_ms: int


@dataclass(frozen=True)
class CriticalPromotionGateDecisionV408:
    allowed: bool
    reason: str
    gate_ids: tuple[str, ...]
    revalidated_gate_ids: tuple[str, ...]
    stale_gate_ids: tuple[str, ...]
    snapshot_decision: CriticalPromotionEvidenceDecisionV407


class GatePromotionAuthorizationLedgerV408:
    """Durable proof that a concrete PASS gate was issued from a known checkpoint."""

    EVENT = "GATE_PROMOTION_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _fingerprint(gate: Gate, checkpoint: int) -> str:
        payload = {
            "gate_id": gate.gate_id,
            "candidate_version": gate.candidate_version,
            "run_id": gate.run_id,
            "input_versions": list(gate.input_versions),
            "checks": list(gate.checks),
            "result": gate.result.value,
            "required_artifacts": list(gate.required_artifacts),
            "evidence_refs": list(gate.evidence_refs),
            "owner": gate.owner,
            "reviewer": gate.reviewer,
            "timestamp": gate.timestamp,
            "expiration": gate.expiration,
            "revalidation_condition": gate.revalidation_condition,
            "dependency_checkpoint": checkpoint,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _dependencies(gate: Gate) -> tuple[str, ...]:
        return tuple(sorted(set(gate.input_versions) | set(gate.evidence_refs) | set(gate.required_artifacts) | {gate.gate_id}))

    def authorize(self, *, gate: Gate, dependency_authority: DependencyInvalidationLedger, recorded_at_ms: int) -> GatePromotionAuthorizationV408:
        if gate.result is not GateResult.PASS:
            raise CriticalPromotionGateErrorV408("GATE_PASS_REQUIRED")
        if recorded_at_ms < 0:
            raise CriticalPromotionGateErrorV408("GATE_AUTHORIZATION_TIMESTAMP_INVALID")
        if dependency_authority.store is not self.store:
            raise CriticalPromotionGateErrorV408("SHARED_EVENT_STORE_REQUIRED")
        checkpoint = dependency_authority.checkpoint()
        dependencies = self._dependencies(gate)
        try:
            dependency_authority.assert_clear(dependencies)
        except DependencyInvalidationBlocked as exc:
            raise CriticalPromotionGateErrorV408("GATE_DEPENDENCY_BLOCKED") from exc
        record = GatePromotionAuthorizationV408(
            authorization_id=f"gate-promotion-auth:{gate.gate_id}:{gate.run_id}",
            gate_id=gate.gate_id,
            run_id=gate.run_id,
            candidate_version=gate.candidate_version,
            dependency_checkpoint=checkpoint,
            gate_fingerprint=self._fingerprint(gate, checkpoint),
            recorded_at_ms=recorded_at_ms,
        )
        payload = {
            "authorization_id": record.authorization_id,
            "gate_id": record.gate_id,
            "run_id": record.run_id,
            "candidate_version": record.candidate_version,
            "dependency_checkpoint": record.dependency_checkpoint,
            "gate_fingerprint": record.gate_fingerprint,
            "recorded_at_ms": record.recorded_at_ms,
            "gate": {
                "gate_id": gate.gate_id,
                "candidate_version": gate.candidate_version,
                "run_id": gate.run_id,
                "input_versions": list(gate.input_versions),
                "checks": list(gate.checks),
                "result": gate.result.value,
                "required_artifacts": list(gate.required_artifacts),
                "evidence_refs": list(gate.evidence_refs),
                "owner": gate.owner,
                "reviewer": gate.reviewer,
                "timestamp": gate.timestamp,
                "expiration": gate.expiration,
                "revalidation_condition": gate.revalidation_condition,
            },
        }
        existing = self.store.get(record.authorization_id)
        if existing is not None:
            if existing.event_type != self.EVENT or dict(existing.payload) != payload:
                raise CriticalPromotionGateErrorV408("GATE_AUTHORIZATION_ID_CONFLICT")
            return record
        self.store.append(
            event_id=record.authorization_id,
            occurred_at_ms=recorded_at_ms,
            event_type=self.EVENT,
            aggregate_id=gate.gate_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise CriticalPromotionGateErrorV408("EVENT_CHAIN_INVALID_AFTER_GATE_AUTHORIZATION")
        return record

    def _find(self, gate_id: str) -> GatePromotionAuthorizationV408 | None:
        matches = [e for e in self.store.iter_events() if e.event_type == self.EVENT and e.aggregate_id == gate_id]
        if not matches:
            return None
        event = max(matches, key=lambda e: e.sequence)
        p = event.payload
        return GatePromotionAuthorizationV408(
            str(p["authorization_id"]), str(p["gate_id"]), str(p["run_id"]),
            str(p["candidate_version"]), int(p["dependency_checkpoint"]),
            str(p["gate_fingerprint"]), int(p["recorded_at_ms"]),
        )

    def _event_for(self, gate_id: str):
        auth = self._find(gate_id)
        if auth is None:
            raise CriticalPromotionGateErrorV408("GATE_PROMOTION_AUTHORIZATION_NOT_FOUND")
        return self.store.get(auth.authorization_id)

    @staticmethod
    def _gate_from_event(event) -> Gate:
        p = event.payload
        try:
            return Gate(
                gate_id=str(p["gate"]["gate_id"]),
                candidate_version=str(p["gate"]["candidate_version"]),
                run_id=str(p["gate"]["run_id"]),
                input_versions=tuple(str(v) for v in p["gate"]["input_versions"]),
                checks=tuple(str(v) for v in p["gate"]["checks"]),
                result=GateResult(str(p["gate"]["result"])),
                required_artifacts=tuple(str(v) for v in p["gate"]["required_artifacts"]),
                evidence_refs=tuple(str(v) for v in p["gate"]["evidence_refs"]),
                owner=str(p["gate"]["owner"]),
                reviewer=None if p["gate"]["reviewer"] is None else str(p["gate"]["reviewer"]),
                timestamp=str(p["gate"]["timestamp"]),
                expiration=None if p["gate"]["expiration"] is None else str(p["gate"]["expiration"]),
                revalidation_condition=str(p["gate"]["revalidation_condition"]),
            )
        except Exception as exc:
            raise CriticalPromotionGateErrorV408("INVALID_GATE_PROMOTION_AUTHORIZATION_PAYLOAD") from exc

    def assert_registered_reusable(self, gate_id: str, dependency_authority: DependencyInvalidationLedger, now_ms: int) -> GatePromotionAuthorizationV408:
        event = self._event_for(gate_id)
        gate = self._gate_from_event(event)
        return self.assert_reusable(gate, dependency_authority, now_ms)

    def assert_reusable(self, gate: Gate, dependency_authority: DependencyInvalidationLedger, now_ms: int) -> GatePromotionAuthorizationV408:
        if dependency_authority.store is not self.store:
            raise CriticalPromotionGateErrorV408("SHARED_EVENT_STORE_REQUIRED")
        auth = self._find(gate.gate_id)
        if auth is None:
            raise CriticalPromotionGateErrorV408("GATE_PROMOTION_AUTHORIZATION_NOT_FOUND")
        if gate.result is not GateResult.PASS:
            raise CriticalPromotionGateErrorV408("GATE_NOT_PASS")
        if auth.run_id != gate.run_id or auth.candidate_version != gate.candidate_version:
            raise CriticalPromotionGateErrorV408("GATE_AUTHORIZATION_BINDING_MISMATCH")
        if auth.gate_fingerprint != self._fingerprint(gate, auth.dependency_checkpoint):
            raise CriticalPromotionGateErrorV408("GATE_AUTHORIZATION_FINGERPRINT_MISMATCH")
        if now_ms < auth.recorded_at_ms:
            raise CriticalPromotionGateErrorV408("GATE_AUTHORIZATION_TIME_TRAVEL")
        dependencies = self._dependencies(gate)
        try:
            dependency_authority.assert_clear(dependencies)
            dependency_authority.assert_unchanged_since(auth.dependency_checkpoint, dependencies)
        except DependencyInvalidationBlocked as exc:
            raise CriticalPromotionGateErrorV408("GATE_REUSE_BLOCKED_AFTER_INVALIDATION") from exc
        except DependencyInvalidationError as exc:
            raise CriticalPromotionGateErrorV408("GATE_REUSE_REQUIRES_RERUN") from exc
        return auth


class CriticalPromotionGatePreflightV408:
    """Strict critical-promotion preflight requiring durable, reusable gate authorization."""

    def __init__(self, *, store: EventStore | None = None, dependency_authority: DependencyInvalidationLedger | None = None) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.dependency_authority.store is not self.store:
            raise CriticalPromotionGateErrorV408("SHARED_EVENT_STORE_REQUIRED")
        self.snapshot_preflight = CriticalPromotionEvidencePreflightV407(
            store=self.store, dependency_authority=self.dependency_authority
        )
        self.gate_authority = GatePromotionAuthorizationLedgerV408(self.store)

    def check(
        self,
        *,
        bundle: PromotionBundle,
        gates: tuple[Gate, ...],
        now: datetime,
    ) -> CriticalPromotionGateDecisionV408:
        if now.tzinfo is None:
            snapshot = self.snapshot_preflight.check(bundle=bundle, now=now)
            return CriticalPromotionGateDecisionV408(False, "NOW_TIMEZONE_REQUIRED", bundle.gate_results, (), bundle.gate_results, snapshot)
        if not self.store.verify_chain():
            snapshot = CriticalPromotionEvidenceDecisionV407(False, "EVENT_CHAIN_INVALID", bundle.evidence_snapshot_id, bundle.bundle_id)
            return CriticalPromotionGateDecisionV408(False, "EVENT_CHAIN_INVALID", bundle.gate_results, (), bundle.gate_results, snapshot)
        by_id = {gate.gate_id: gate for gate in gates}
        missing = tuple(gate_id for gate_id in bundle.gate_results if gate_id not in by_id)
        if missing:
            snapshot = self.snapshot_preflight.check(bundle=bundle, now=now)
            return CriticalPromotionGateDecisionV408(False, "GATE_OBJECT_MISSING:" + ",".join(missing), bundle.gate_results, (), missing, snapshot)

        revalidated: list[str] = []
        stale: list[str] = []
        for gate_id in bundle.gate_results:
            try:
                self.gate_authority.assert_reusable(by_id[gate_id], self.dependency_authority, int(now.timestamp() * 1000))
            except CriticalPromotionGateErrorV408:
                stale.append(gate_id)
            else:
                revalidated.append(gate_id)

        snapshot = self.snapshot_preflight.check(bundle=bundle, now=now)
        blockers = []
        if stale:
            blockers.append("GATE_REVALIDATION_REQUIRED:" + ",".join(stale))
        if not snapshot.allowed:
            blockers.append("SNAPSHOT:" + snapshot.reason)
        if blockers:
            return CriticalPromotionGateDecisionV408(False, ";".join(blockers), bundle.gate_results, tuple(revalidated), tuple(stale), snapshot)
        return CriticalPromotionGateDecisionV408(True, "CRITICAL_PROMOTION_GATE_AND_SNAPSHOT_PRECHECK_OK", bundle.gate_results, tuple(revalidated), (), snapshot)

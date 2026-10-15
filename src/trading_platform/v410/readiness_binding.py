from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256

from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationError,
    DependencyInvalidationLedger,
)
from trading_platform.v360.readiness_evidence import (
    EvidenceResult,
    EvidenceSourceKind,
    EvidenceState,
    ReadinessEvidence,
    ReadinessEvidenceLedger,
    REQUIRED_EVIDENCE_CLASSES,
)
from trading_platform.v408.gate_promotion import (
    CriticalPromotionGateDecisionV408,
)
from trading_platform.v409.production_readiness import (
    ProductionReadinessAuthorityV409,
    ProductionReadinessAuthorityErrorV409,
    ProductionReadinessDecisionV409,
)
from trading_platform.gates.contracts import Gate


class ProductionReadinessRevalidationErrorV410(ValueError):
    __test__ = False


@dataclass(frozen=True)
class ReadinessBindingRecordV410:
    readiness_id: str
    bundle_id: str
    evidence_snapshot_id: str
    scope: str
    evidence_ids: tuple[str, ...]
    evidence_fingerprints: tuple[tuple[str, str], ...]
    human_review_id: str
    approval_id: str
    application_preflight_fingerprint: str
    dependency_checkpoint: int
    assessed_at_ms: int

    @property
    def binding_fingerprint(self) -> str:
        return sha256_json(
            {
                "readiness_id": self.readiness_id,
                "bundle_id": self.bundle_id,
                "evidence_snapshot_id": self.evidence_snapshot_id,
                "scope": self.scope,
                "evidence_ids": list(self.evidence_ids),
                "evidence_fingerprints": [list(x) for x in self.evidence_fingerprints],
                "human_review_id": self.human_review_id,
                "approval_id": self.approval_id,
                "application_preflight_fingerprint": self.application_preflight_fingerprint,
                "dependency_checkpoint": self.dependency_checkpoint,
                "assessed_at_ms": self.assessed_at_ms,
            }
        )


@dataclass(frozen=True)
class ReadinessBindingDecisionV410:
    allowed: bool
    status: str
    reason: str
    bundle_id: str
    scope: str
    evidence_ids: tuple[str, ...]
    readiness_id: str | None
    human_review_id: str | None
    approval_id: str
    application_preflight: CriticalPromotionGateDecisionV408 | None

    @property
    def production_ready(self) -> bool:
        return self.allowed and self.status == "PRODUCTION_READY"


class ProductionReadinessRevalidationAuthorityV410:
    """Exact-scope, exact-evidence readiness binding above V4.9.

    V4.10 does not create external evidence. It takes the already-tested V4.9
    readiness decision and records a stronger binding that is sensitive to:
    exact readiness scope, exact evidence identities, and exact current evidence
    fingerprints. Revalidation fails closed when any of these change.
    """

    EVENT_TYPE = "PRODUCTION_READINESS_BOUND_V410"

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority or DependencyInvalidationLedger(self.store)
        if self.dependency_authority.store is not self.store:
            raise ProductionReadinessRevalidationErrorV410("SHARED_EVENT_STORE_REQUIRED")
        self.v409 = ProductionReadinessAuthorityV409(
            store=self.store,
            dependency_authority=self.dependency_authority,
        )
        self.evidence_ledger = ReadinessEvidenceLedger(self.store)

    @staticmethod
    def _utc_ms(now: datetime) -> int:
        if now.tzinfo is None:
            raise ProductionReadinessRevalidationErrorV410("NOW_TIMEZONE_REQUIRED")
        return int(now.astimezone(timezone.utc).timestamp() * 1000)

    @staticmethod
    def _bundle_dependencies(
        bundle: PromotionBundle,
        evidence_ids: tuple[str, ...],
        human_review_id: str,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(
                    (
                        bundle.bundle_id,
                        bundle.evidence_snapshot_id,
                        *bundle.gate_results,
                        *bundle.artifact_hashes,
                        bundle.strategy_version,
                        bundle.model_version,
                        bundle.feature_version,
                        bundle.target_version,
                        bundle.configuration_version,
                        bundle.execution_model_version,
                        bundle.code_version,
                        bundle.approval_id,
                        bundle.rollback_target,
                        bundle.content_hash,
                        *evidence_ids,
                        human_review_id,
                    )
                )
            )
        )

    @staticmethod
    def _preflight_fingerprint(decision: ProductionReadinessDecisionV409) -> str:
        if decision.application_preflight is None:
            raise ProductionReadinessRevalidationErrorV410("APPLICATION_PREFLIGHT_MISSING")
        return ProductionReadinessAuthorityV409._preflight_fingerprint(decision.application_preflight)

    @staticmethod
    def _evidence_fingerprint(evidence: ReadinessEvidence) -> str:
        return evidence.fingerprint()

    def _current_evidence(
        self,
        *,
        evidence_ids: tuple[str, ...],
        scope: str,
        now_ms: int,
    ) -> tuple[ReadinessEvidence, ...]:
        items: list[ReadinessEvidence] = []
        for evidence_id in evidence_ids:
            item = self.evidence_ledger.get(evidence_id)
            if item is None:
                raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_NOT_FOUND")
            if item.scope != scope:
                raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_SCOPE_MISMATCH")
            if item.state is not EvidenceState.VERIFIED:
                raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_NOT_VERIFIED")
            if item.result is not EvidenceResult.PASS:
                raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_NOT_PASS")
            if item.source_kind is not EvidenceSourceKind.EXTERNAL:
                raise ProductionReadinessRevalidationErrorV410("EXTERNAL_READINESS_EVIDENCE_REQUIRED")
            if not (item.valid_from_ms <= now_ms < item.expires_at_ms):
                raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_EXPIRED")
            items.append(item)
        if len({x.evidence_id for x in items}) != len(items):
            raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_ID_DUPLICATE")
        return tuple(sorted(items, key=lambda x: x.evidence_id))

    def _record_from_v409(
        self,
        *,
        decision: ProductionReadinessDecisionV409,
        bundle: PromotionBundle,
        scope: str,
        now_ms: int,
        dependency_checkpoint: int,
    ) -> ReadinessBindingRecordV410:
        current = self._current_evidence(
            evidence_ids=tuple(sorted(decision.evidence_ids)),
            scope=scope,
            now_ms=now_ms,
        )
        evidence_ids = tuple(sorted(item.evidence_id for item in current))
        if evidence_ids != tuple(sorted(decision.evidence_ids)):
            raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_SET_CHANGED")
        deps = self._bundle_dependencies(bundle, evidence_ids, decision.human_review_id or "")
        try:
            self.dependency_authority.assert_clear(deps)
            self.dependency_authority.assert_unchanged_since(dependency_checkpoint, deps)
        except DependencyInvalidationBlocked as exc:
            raise ProductionReadinessRevalidationErrorV410("DEPENDENCY_STALE") from exc
        except DependencyInvalidationError as exc:
            raise ProductionReadinessRevalidationErrorV410("DEPENDENCY_REQUIRES_REVALIDATION") from exc

        return ReadinessBindingRecordV410(
            readiness_id=f"production-readiness-v410:{decision.readiness_id.removeprefix('production-readiness:')}",
            bundle_id=bundle.bundle_id,
            evidence_snapshot_id=bundle.evidence_snapshot_id,
            scope=scope,
            evidence_ids=evidence_ids,
            evidence_fingerprints=tuple((x.evidence_id, self._evidence_fingerprint(x)) for x in current),
            human_review_id=str(decision.human_review_id),
            approval_id=decision.approval_id,
            application_preflight_fingerprint=self._preflight_fingerprint(decision),
            dependency_checkpoint=dependency_checkpoint,
            assessed_at_ms=now_ms,
        )

    def assess(
        self,
        *,
        bundle: PromotionBundle,
        gates: tuple[Gate, ...],
        approval: Approval,
        human_review_id: str,
        scope: str,
        now: datetime,
        assessment_id: str,
        record: bool = True,
    ) -> ReadinessBindingDecisionV410:
        try:
            bundle.validate()
            approval.validate(now)
            if not scope:
                raise ProductionReadinessRevalidationErrorV410("READINESS_SCOPE_REQUIRED")
        except (ValueError, ProductionReadinessRevalidationErrorV410) as exc:
            return ReadinessBindingDecisionV410(
                False, "BLOCKED", f"INPUT:{exc}", bundle.bundle_id, scope, (), None,
                human_review_id, bundle.approval_id, None,
            )

        checkpoint = self.dependency_authority.checkpoint()
        try:
            self.dependency_authority.assert_clear(
                self._bundle_dependencies(bundle, (), human_review_id)
            )
        except (DependencyInvalidationBlocked, DependencyInvalidationError) as exc:
            return ReadinessBindingDecisionV410(
                False, "BLOCKED", f"DEPENDENCY:{type(exc).__name__}", bundle.bundle_id, scope, (), None,
                human_review_id, bundle.approval_id, None,
            )

        try:
            decision = self.v409.assess(
                bundle=bundle,
                gates=gates,
                approval=approval,
                human_review_id=human_review_id,
                scope=scope,
                now=now,
                assessment_id=assessment_id,
                record=False,
            )
        except ProductionReadinessAuthorityErrorV409 as exc:
            return ReadinessBindingDecisionV410(
                False, "BLOCKED", f"V409:{exc}", bundle.bundle_id, scope, (), None,
                human_review_id, bundle.approval_id, None,
            )

        if not decision.production_ready:
            return ReadinessBindingDecisionV410(
                False, "BLOCKED", decision.reason, bundle.bundle_id, scope,
                tuple(sorted(decision.evidence_ids)), None,
                decision.human_review_id, decision.approval_id, decision.application_preflight,
            )

        now_ms = self._utc_ms(now)
        try:
            record_obj = self._record_from_v409(
                decision=decision,
                bundle=bundle,
                scope=scope,
                now_ms=now_ms,
                dependency_checkpoint=checkpoint,
            )
        except ProductionReadinessRevalidationErrorV410 as exc:
            return ReadinessBindingDecisionV410(
                False, "BLOCKED", str(exc), bundle.bundle_id, scope,
                tuple(sorted(decision.evidence_ids)), None,
                decision.human_review_id, decision.approval_id, decision.application_preflight,
            )
        if record:
            self._persist(record_obj)

        return ReadinessBindingDecisionV410(
            True, "PRODUCTION_READY", "PRODUCTION_READINESS_EXACT_BINDING_VERIFIED",
            bundle.bundle_id, scope, record_obj.evidence_ids, record_obj.readiness_id,
            record_obj.human_review_id, record_obj.approval_id, decision.application_preflight,
        )

    def _persist(self, record: ReadinessBindingRecordV410) -> None:
        payload = {
            "readiness_id": record.readiness_id,
            "bundle_id": record.bundle_id,
            "evidence_snapshot_id": record.evidence_snapshot_id,
            "scope": record.scope,
            "evidence_ids": list(record.evidence_ids),
            "evidence_fingerprints": [list(x) for x in record.evidence_fingerprints],
            "human_review_id": record.human_review_id,
            "approval_id": record.approval_id,
            "application_preflight_fingerprint": record.application_preflight_fingerprint,
            "dependency_checkpoint": record.dependency_checkpoint,
            "assessed_at_ms": record.assessed_at_ms,
            "binding_fingerprint": record.binding_fingerprint,
            "source": "V410_EXACT_READINESS_BINDING",
        }
        existing = self.store.get(record.readiness_id)
        if existing is not None:
            if existing.event_type != self.EVENT_TYPE or dict(existing.payload) != payload:
                raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_RECORD_CONFLICT")
            return
        self.store.append(
            event_id=record.readiness_id,
            occurred_at_ms=record.assessed_at_ms,
            event_type=self.EVENT_TYPE,
            aggregate_id=record.bundle_id,
            payload=payload,
        )
        if not self.store.verify_chain():
            raise ProductionReadinessRevalidationErrorV410("EVENT_CHAIN_INVALID_AFTER_BINDING")

    def get(self, readiness_id: str) -> ReadinessBindingRecordV410 | None:
        event = self.store.get(readiness_id)
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        p = event.payload
        record = ReadinessBindingRecordV410(
            readiness_id=str(p["readiness_id"]),
            bundle_id=str(p["bundle_id"]),
            evidence_snapshot_id=str(p["evidence_snapshot_id"]),
            scope=str(p["scope"]),
            evidence_ids=tuple(str(v) for v in p["evidence_ids"]),
            evidence_fingerprints=tuple((str(v[0]), str(v[1])) for v in p["evidence_fingerprints"]),
            human_review_id=str(p["human_review_id"]),
            approval_id=str(p["approval_id"]),
            application_preflight_fingerprint=str(p["application_preflight_fingerprint"]),
            dependency_checkpoint=int(p["dependency_checkpoint"]),
            assessed_at_ms=int(p["assessed_at_ms"]),
        )
        if str(p.get("binding_fingerprint", "")) != record.binding_fingerprint:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_FINGERPRINT_MISMATCH")
        return record

    def assert_verified(
        self,
        readiness_id: str,
        *,
        bundle: PromotionBundle,
        gates: tuple[Gate, ...],
        approval: Approval,
        scope: str,
        now: datetime,
    ) -> ReadinessBindingRecordV410:
        record = self.get(readiness_id)
        if record is None:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_NOT_FOUND")
        if record.bundle_id != bundle.bundle_id or record.evidence_snapshot_id != bundle.evidence_snapshot_id:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_BUNDLE_MISMATCH")
        if record.scope != scope:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_SCOPE_MISMATCH")
        if record.approval_id != approval.approval_id or bundle.approval_id != approval.approval_id:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_APPROVAL_MISMATCH")
        if not self.store.verify_chain():
            raise ProductionReadinessRevalidationErrorV410("EVENT_CHAIN_INVALID")

        now_ms = self._utc_ms(now)
        current = self._current_evidence(
            evidence_ids=record.evidence_ids,
            scope=scope,
            now_ms=now_ms,
        )
        current_fingerprints = tuple((x.evidence_id, self._evidence_fingerprint(x)) for x in current)
        if current_fingerprints != record.evidence_fingerprints:
            raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_FINGERPRINT_CHANGED")

        dependencies = self._bundle_dependencies(bundle, record.evidence_ids, record.human_review_id)
        try:
            self.dependency_authority.assert_clear(dependencies)
            self.dependency_authority.assert_unchanged_since(record.dependency_checkpoint, dependencies)
        except DependencyInvalidationBlocked as exc:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_STALE_AFTER_INVALIDATION") from exc
        except DependencyInvalidationError as exc:
            raise ProductionReadinessRevalidationErrorV410("READINESS_BINDING_REQUIRES_REVALIDATION") from exc

        decision = self.v409.assess(
            bundle=bundle,
            gates=gates,
            approval=approval,
            human_review_id=record.human_review_id,
            scope=scope,
            now=now,
            assessment_id=readiness_id.removeprefix("production-readiness-v410:"),
            record=False,
        )
        if not decision.production_ready:
            raise ProductionReadinessRevalidationErrorV410(
                "READINESS_REVALIDATION_FAILED:" + decision.reason
            )
        if tuple(sorted(decision.evidence_ids)) != record.evidence_ids:
            raise ProductionReadinessRevalidationErrorV410("READINESS_EVIDENCE_SET_CHANGED")
        if decision.human_review_id != record.human_review_id:
            raise ProductionReadinessRevalidationErrorV410("READINESS_HUMAN_REVIEW_MISMATCH")
        if self._preflight_fingerprint(decision) != record.application_preflight_fingerprint:
            raise ProductionReadinessRevalidationErrorV410("READINESS_PREFLIGHT_FINGERPRINT_CHANGED")
        return record

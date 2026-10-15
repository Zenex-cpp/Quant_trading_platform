from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping, Any

from trading_platform.v21.event_store import EventStore
from trading_platform.v411.operational_evidence import (
    OperationalEvidenceManifestAuthorityV411,
    OperationalEvidenceManifestErrorV411,
)
from trading_platform.v412.external_review_bridge import (
    ExternalReviewAttestationV393,
    ExternalReviewBridgeAuthorityV412,
    ExternalReviewBridgeErrorV412,
)
from trading_platform.v415.production_readiness_seal import (
    ProductionReadinessSealAuthorityV415,
    ProductionReadinessSealErrorV415,
)


class OperationalReadinessConvergenceErrorV416(ValueError):
    __test__ = False


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class OperationalReadinessConvergenceDecisionV416:
    allowed: bool
    status: str
    reason: str
    convergence_id: str
    bundle_id: str
    package_id: str
    manifest_hash: str
    bridge_id: str
    seal_id: str
    evidence_ids: tuple[str, ...]


class OperationalReadinessConvergenceAuthorityV416:
    """Converges external operational evidence into the already verified V4.15 seal.

    This authority does not manufacture external evidence, execute infrastructure,
    contact venues, deploy credentials, or set any runtime production-readiness flag.
    It only proves that the same bundle is covered by the complete V4.11 manifest,
    the V4.12 externally verified bridge, and the V4.15 final application seal.
    """

    EVENT_TYPE = "OPERATIONAL_READINESS_CONVERGED_V416"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self.manifest_authority = OperationalEvidenceManifestAuthorityV411(self.store)
        self.bridge_authority = ExternalReviewBridgeAuthorityV412(self.store)
        self.seal_authority = ProductionReadinessSealAuthorityV415(self.store)

    def _require_seal(self, *, seal_id: str, bundle_id: str):
        try:
            self.seal_authority.assert_valid(seal_id)
        except ProductionReadinessSealErrorV415 as exc:
            raise OperationalReadinessConvergenceErrorV416(f"SEAL:{exc}") from exc
        event = self.seal_authority.get(seal_id)
        if event is None:
            raise OperationalReadinessConvergenceErrorV416("READINESS_SEAL_REQUIRED")
        if str(event.payload.get("bundle_id")) != bundle_id:
            raise OperationalReadinessConvergenceErrorV416("SEAL_BUNDLE_MISMATCH")
        if str(event.payload.get("status")) != "VERIFIED":
            raise OperationalReadinessConvergenceErrorV416("READINESS_SEAL_NOT_VERIFIED")
        return event

    def converge(
        self,
        *,
        convergence_id: str,
        bundle_id: str,
        package_id: str,
        manifest: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        bridge_id: str,
        seal_id: str,
        now_ms: int,
    ) -> OperationalReadinessConvergenceDecisionV416:
        if not convergence_id or not bundle_id or not package_id or not bridge_id or not seal_id:
            raise OperationalReadinessConvergenceErrorV416("CONVERGENCE_IDENTIFIERS_REQUIRED")
        if not isinstance(now_ms, int):
            raise OperationalReadinessConvergenceErrorV416("NOW_MS_MUST_BE_INT")

        try:
            manifest_decision = self.manifest_authority.admit(manifest)
        except OperationalEvidenceManifestErrorV411 as exc:
            raise OperationalReadinessConvergenceErrorV416(f"MANIFEST:{exc}") from exc
        if manifest_decision.package_id != package_id:
            raise OperationalReadinessConvergenceErrorV416("MANIFEST_PACKAGE_MISMATCH")

        expected_bridge_id = f"external-review-bridge-v412:{package_id}"
        if bridge_id != expected_bridge_id:
            raise OperationalReadinessConvergenceErrorV416("BRIDGE_ID_MISMATCH")
        try:
            bridge = self.bridge_authority.assert_verified(
                bridge_id,
                manifest=manifest,
                review=review,
                now_ms=now_ms,
            )
        except ExternalReviewBridgeErrorV412 as exc:
            raise OperationalReadinessConvergenceErrorV416(f"BRIDGE:{exc}") from exc

        if bridge.manifest_hash != manifest_decision.manifest_hash:
            raise OperationalReadinessConvergenceErrorV416("BRIDGE_MANIFEST_HASH_MISMATCH")
        if bridge.package_id != package_id:
            raise OperationalReadinessConvergenceErrorV416("BRIDGE_PACKAGE_MISMATCH")
        if bridge.evidence_ids != manifest_decision.evidence_ids:
            raise OperationalReadinessConvergenceErrorV416("BRIDGE_EVIDENCE_SET_MISMATCH")

        seal_event = self._require_seal(seal_id=seal_id, bundle_id=bundle_id)
        if str(seal_event.payload.get("critical_readiness_id")) == "":
            raise OperationalReadinessConvergenceErrorV416("SEAL_CRITICAL_READINESS_BINDING_MISSING")

        event_id = f"operational-readiness-convergence-v416:{convergence_id}"
        payload = {
            "convergence_id": convergence_id,
            "bundle_id": bundle_id,
            "package_id": package_id,
            "manifest_hash": manifest_decision.manifest_hash,
            "bridge_id": bridge_id,
            "bridge_event_hash": self.store.get(bridge_id).event_hash if self.store.get(bridge_id) else "",
            "review_id": review.review_id,
            "review_fingerprint": review.fingerprint,
            "seal_id": seal_id,
            "seal_event_hash": seal_event.event_hash,
            "evidence_ids": list(manifest_decision.evidence_ids),
            "status": "VERIFIED",
            "activation_flag": "NOT_SET",
        }
        payload["fingerprint"] = _canonical_hash(payload)

        existing = self.store.get(event_id)
        if existing is None:
            occurred_at = max(int(seal_event.occurred_at_ms), int(bridge.verified_at_ms))
            self.store.append(
                event_id=event_id,
                occurred_at_ms=occurred_at,
                event_type=self.EVENT_TYPE,
                aggregate_id=bundle_id,
                payload=payload,
            )
        elif dict(existing.payload) != payload:
            raise OperationalReadinessConvergenceErrorV416("CONVERGENCE_EVENT_ID_CONFLICT")

        return OperationalReadinessConvergenceDecisionV416(
            allowed=True,
            status="VERIFIED",
            reason="OPERATIONAL_READINESS_EXTERNAL_EVIDENCE_CONVERGED",
            convergence_id=event_id,
            bundle_id=bundle_id,
            package_id=package_id,
            manifest_hash=manifest_decision.manifest_hash,
            bridge_id=bridge_id,
            seal_id=seal_id,
            evidence_ids=manifest_decision.evidence_ids,
        )

    def get(self, convergence_id: str):
        event = self.store.get(f"operational-readiness-convergence-v416:{convergence_id}")
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _canonical_hash(payload):
            raise OperationalReadinessConvergenceErrorV416("CONVERGENCE_FINGERPRINT_MISMATCH")
        return event

    def assert_valid(self, convergence_id: str) -> None:
        event = self.get(convergence_id)
        if event is None or str(event.payload.get("status")) != "VERIFIED":
            raise OperationalReadinessConvergenceErrorV416("CONVERGENCE_NOT_VALID")
        if str(event.payload.get("activation_flag")) != "NOT_SET":
            raise OperationalReadinessConvergenceErrorV416("ACTIVATION_FLAG_MUST_NOT_BE_SET")

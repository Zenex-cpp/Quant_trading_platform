"""V4.14 ordering gate between V4.11, V4.13 and V4.12."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v393.external_review_authority import ExternalReviewAttestationV393
from trading_platform.v394.cryptographic_attestation import SignedReviewEnvelopeV394, TrustAnchorV394
from trading_platform.v411.operational_evidence import OperationalEvidenceManifestAuthorityV411
from trading_platform.v412.external_review_bridge import ExternalReviewBridgeAuthorityV412
from trading_platform.v413.crypto_review import PromotionCryptoReviewAuthorityV413, PromotionCryptoReviewErrorV413


class PromotionCryptoGateErrorV414(ValueError):
    __test__ = False


def _hash(value: Any) -> str:
    import json
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class PromotionCryptoGateDecisionV414:
    allowed: bool
    reason: str
    gate_id: str
    crypto_review_gate_id: str
    bridge_id: str | None
    status: str


class PromotionCryptoGateAuthorityV414:
    EVENT_TYPE = "PROMOTION_CRYPTO_GATE_VERIFIED_V414"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self.manifest_authority = OperationalEvidenceManifestAuthorityV411(self.store)
        self.crypto_authority = PromotionCryptoReviewAuthorityV413(self.store)
        self.bridge_authority = ExternalReviewBridgeAuthorityV412(self.store)

    def admit(
        self,
        *,
        manifest: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        envelope: SignedReviewEnvelopeV394,
        trust_anchor: TrustAnchorV394,
        trust_anchor_attestation_id: str,
        now_ms: int,
    ) -> PromotionCryptoGateDecisionV414:
        package_id = str(manifest.get("package_id", ""))
        gate_id = f"promotion-crypto-gate-v414:{package_id}"
        manifest_decision = self.manifest_authority.admit(manifest)
        existing = self.store.get(gate_id)
        if existing is not None:
            if existing.event_type != self.EVENT_TYPE:
                raise PromotionCryptoGateErrorV414("CRYPTO_GATE_EVENT_ID_CONFLICT")
            package = self.bridge_authority._normalized_package(manifest)
            try:
                crypto = self.crypto_authority.verify(
                    package=package,
                    review=review,
                    envelope=envelope,
                    trust_anchor=trust_anchor,
                    trust_anchor_attestation_id=trust_anchor_attestation_id,
                    now_ms=now_ms,
                )
                if not crypto.allowed:
                    raise PromotionCryptoGateErrorV414("CRYPTO_REVIEW_REQUIRED")
                bridge_id = str(existing.payload.get("bridge_id", ""))
                self.bridge_authority.assert_verified(bridge_id, manifest=manifest, review=review, now_ms=now_ms)
                self.assert_valid(gate_id)
                return PromotionCryptoGateDecisionV414(True, "PROMOTION_CRYPTO_GATE_VERIFIED", gate_id, str(existing.payload["crypto_review_gate_id"]), bridge_id, "VERIFIED")
            except PromotionCryptoReviewErrorV413 as exc:
                raise PromotionCryptoGateErrorV414(str(exc)) from exc
        try:
            package = self.bridge_authority._normalized_package(manifest)
            crypto = self.crypto_authority.verify(
                package=package,
                review=review,
                envelope=envelope,
                trust_anchor=trust_anchor,
                trust_anchor_attestation_id=trust_anchor_attestation_id,
                now_ms=now_ms,
            )
            if not crypto.allowed:
                raise PromotionCryptoGateErrorV414("CRYPTO_REVIEW_REQUIRED")
            bridge = self.bridge_authority.assess(manifest=manifest, review=review, now_ms=now_ms, record=True)
            body = {
                "gate_id": gate_id,
                "package_id": package_id,
                "manifest_hash": manifest_decision.manifest_hash,
                "crypto_review_gate_id": crypto.gate_id,
                "crypto_review_event_id": crypto.crypto_event_id,
                "bridge_id": bridge.bridge_id,
                "review_id": review.review_id,
                "review_hash": review.review_hash,
                "signature_hash": envelope.signature_hash,
                "evidence_ids": list(manifest_decision.evidence_ids),
                "status": "VERIFIED",
            }
            body["fingerprint"] = _hash(body)
            existing = self.store.get(gate_id)
            if existing is None:
                self.store.append(event_id=gate_id, occurred_at_ms=now_ms, event_type=self.EVENT_TYPE, aggregate_id=package_id, payload=body)
            elif dict(existing.payload) != body:
                raise PromotionCryptoGateErrorV414("CRYPTO_GATE_EVENT_ID_CONFLICT")
            return PromotionCryptoGateDecisionV414(True, "PROMOTION_CRYPTO_GATE_VERIFIED", gate_id, crypto.gate_id, bridge.bridge_id, "VERIFIED")
        except PromotionCryptoReviewErrorV413 as exc:
            raise PromotionCryptoGateErrorV414(str(exc)) from exc

    def assert_valid(self, gate_id: str) -> None:
        event = self.store.get(gate_id)
        if event is None or event.event_type != self.EVENT_TYPE:
            raise PromotionCryptoGateErrorV414("PROMOTION_CRYPTO_GATE_NOT_FOUND")
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _hash(payload):
            raise PromotionCryptoGateErrorV414("PROMOTION_CRYPTO_GATE_FINGERPRINT_MISMATCH")
        crypto_event = self.store.get(str(payload.get("crypto_review_gate_id")))
        bridge_event = self.store.get(str(payload.get("bridge_id")))
        if crypto_event is None or bridge_event is None:
            raise PromotionCryptoGateErrorV414("PROMOTION_CRYPTO_GATE_PREDECESSOR_MISSING")
        if crypto_event.event_type != "PROMOTION_CRYPTO_REVIEW_VERIFIED_V413":
            raise PromotionCryptoGateErrorV414("PROMOTION_CRYPTO_GATE_CRYPTO_PREDECESSOR_INVALID")
        if bridge_event.event_type != "OPERATIONAL_EVIDENCE_EXTERNAL_REVIEW_BRIDGED_V412":
            raise PromotionCryptoGateErrorV414("PROMOTION_CRYPTO_GATE_BRIDGE_PREDECESSOR_INVALID")

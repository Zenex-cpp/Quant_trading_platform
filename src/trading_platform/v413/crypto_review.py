"""V4.13 bridge: trust-anchor attestation + cryptographic review verification.

This layer does not manufacture external assurance. It only accepts an already
accepted V3.95 trust-anchor attestation and a successful V3.94 verification, then
persists a durable binding between those results.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v394.cryptographic_attestation import (
    CryptographicAttestationAuthorityV394,
    SignedReviewEnvelopeV394,
    TrustAnchorV394,
)
from trading_platform.v393.external_review_authority import ExternalReviewAttestationV393


class PromotionCryptoReviewErrorV413(ValueError):
    __test__ = False


def _fingerprint(value: Mapping[str, Any]) -> str:
    import json
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class PromotionCryptoReviewDecisionV413:
    allowed: bool
    reason: str
    gate_id: str
    crypto_event_id: str | None
    trust_attestation_id: str
    status: str


class PromotionCryptoReviewAuthorityV413:
    EVENT_TYPE = "PROMOTION_CRYPTO_REVIEW_VERIFIED_V413"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def verify(
        self,
        *,
        package: Mapping[str, Any],
        review: ExternalReviewAttestationV393,
        envelope: SignedReviewEnvelopeV394,
        trust_anchor: TrustAnchorV394,
        trust_anchor_attestation_id: str,
        now_ms: int,
    ) -> PromotionCryptoReviewDecisionV413:
        gate_id = f"promotion-crypto-review-v413:{envelope.envelope_id}"
        try:
            event = self.store.get(f"trust-anchor-attestation:{trust_anchor_attestation_id}:accepted")
            if event is None or event.event_type != "TRUST_ANCHOR_ATTESTATION_ACCEPTED":
                raise PromotionCryptoReviewErrorV413("TRUST_ANCHOR_ATTESTATION_REQUIRED")
            payload = dict(event.payload)
            if payload.get("status") != "VERIFIED":
                raise PromotionCryptoReviewErrorV413("TRUST_ANCHOR_ATTESTATION_NOT_VERIFIED")
            if str(payload.get("registry_version")) != trust_anchor.registry_version:
                raise PromotionCryptoReviewErrorV413("TRUST_REGISTRY_VERSION_MISMATCH")
            decision = CryptographicAttestationAuthorityV394(self.store).verify(
                package=package,
                review=review,
                envelope=envelope,
                trust_anchor=trust_anchor,
                now_ms=now_ms,
            )
            if not decision.allowed or decision.verification.value != "VERIFIED":
                raise PromotionCryptoReviewErrorV413(f"CRYPTO_VERIFICATION:{decision.reason}")
            body = {
                "gate_id": gate_id,
                "envelope_id": envelope.envelope_id,
                "review_id": review.review_id,
                "trust_anchor_attestation_id": trust_anchor_attestation_id,
                "package_id": str(package["package_id"]),
                "package_hash": str(package["package_hash"]),
                "review_hash": review.review_hash,
                "signature_hash": envelope.signature_hash,
                "registry_version": trust_anchor.registry_version,
                "registry_attestation_event_hash": event.event_hash,
                "status": "VERIFIED",
            }
            body["fingerprint"] = _fingerprint(body)
            existing = self.store.get(gate_id)
            if existing is None:
                self.store.append(
                    event_id=gate_id,
                    occurred_at_ms=now_ms,
                    event_type=self.EVENT_TYPE,
                    aggregate_id=str(package["package_id"]),
                    payload=body,
                )
            elif dict(existing.payload) != body:
                raise PromotionCryptoReviewErrorV413("CRYPTO_REVIEW_EVENT_ID_CONFLICT")
            return PromotionCryptoReviewDecisionV413(True, "PROMOTION_CRYPTO_REVIEW_VERIFIED", gate_id, f"crypto-review:{envelope.envelope_id}:verified", trust_anchor_attestation_id, "VERIFIED")
        except PromotionCryptoReviewErrorV413:
            raise

    def get(self, gate_id: str):
        return self.store.get(gate_id)

    def assert_valid(self, gate_id: str) -> None:
        event = self.store.get(gate_id)
        if event is None or event.event_type != self.EVENT_TYPE:
            raise PromotionCryptoReviewErrorV413("PROMOTION_CRYPTO_REVIEW_NOT_FOUND")
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _fingerprint(payload):
            raise PromotionCryptoReviewErrorV413("PROMOTION_CRYPTO_REVIEW_FINGERPRINT_MISMATCH")
        for key in ("package_hash", "review_hash", "signature_hash", "registry_version", "trust_anchor_attestation_id"):
            if not payload.get(key):
                raise PromotionCryptoReviewErrorV413(f"PROMOTION_CRYPTO_REVIEW_{key.upper()}_MISSING")

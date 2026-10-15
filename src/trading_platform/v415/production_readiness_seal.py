"""V4.15 final readiness seal.

The authority consumes already verified durable predecessors. It does not execute,
deploy, mutate Testnet/Production, or set any runtime ``production_ready`` flag.
Its output is an immutable audit seal stating that the predecessor contract chain
was complete at a specific point in time.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v414.promotion_crypto_gate import PromotionCryptoGateAuthorityV414, PromotionCryptoGateErrorV414


class ProductionReadinessSealErrorV415(ValueError):
    __test__ = False


def _hash(value: Any) -> str:
    import json
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ProductionReadinessSealDecisionV415:
    allowed: bool
    reason: str
    seal_id: str
    bundle_id: str
    crypto_gate_id: str
    critical_readiness_id: str
    status: str


class ProductionReadinessSealAuthorityV415:
    EVENT_TYPE = "PRODUCTION_READINESS_SEAL_VERIFIED_V415"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self.crypto_gate = PromotionCryptoGateAuthorityV414(self.store)

    @staticmethod
    def _require_verified(store: EventStore, event_id: str, event_type: str, reason: str):
        event = store.get(event_id)
        if event is None:
            raise ProductionReadinessSealErrorV415(reason)
        if event.event_type != event_type or str(event.payload.get("status")) != "VERIFIED":
            raise ProductionReadinessSealErrorV415(reason)
        return event

    def seal(
        self,
        *,
        seal_id: str,
        bundle_id: str,
        crypto_gate_id: str,
        critical_readiness_id: str,
        dependency_keys: tuple[str, ...] = (),
    ) -> ProductionReadinessSealDecisionV415:
        if not seal_id or not bundle_id:
            raise ProductionReadinessSealErrorV415("READINESS_SEAL_IDENTIFIERS_REQUIRED")
        try:
            self.crypto_gate.assert_valid(crypto_gate_id)
            crypto_event = self._require_verified(
                self.store,
                crypto_gate_id,
                "PROMOTION_CRYPTO_GATE_VERIFIED_V414",
                "CRYPTO_GATE_REQUIRED",
            )
            critical_event = self._require_verified(
                self.store,
                f"critical-promotion-readiness:{critical_readiness_id}:accepted",
                "CRITICAL_PROMOTION_READINESS_ACCEPTED",
                "CRITICAL_PROMOTION_READINESS_REQUIRED",
            )
            if str(critical_event.payload.get("bundle_id")) != bundle_id:
                raise ProductionReadinessSealErrorV415("CRITICAL_READINESS_BUNDLE_MISMATCH")
            event_id = f"production-readiness-seal-v415:{seal_id}"
            payload = {
                "seal_id": seal_id,
                "bundle_id": bundle_id,
                "crypto_gate_id": crypto_gate_id,
                "critical_readiness_id": critical_readiness_id,
                "crypto_gate_event_hash": crypto_event.event_hash,
                "critical_readiness_event_hash": critical_event.event_hash,
                "dependency_keys": list(dependency_keys),
                "status": "VERIFIED",
                "activation_flag": "NOT_SET",
            }
            payload["fingerprint"] = _hash(payload)
            existing = self.store.get(event_id)
            if existing is None:
                occurred_at = max(int(crypto_event.occurred_at_ms), int(critical_event.occurred_at_ms))
                self.store.append(event_id=event_id, occurred_at_ms=occurred_at, event_type=self.EVENT_TYPE, aggregate_id=bundle_id, payload=payload)
            elif dict(existing.payload) != payload:
                raise ProductionReadinessSealErrorV415("READINESS_SEAL_EVENT_ID_CONFLICT")
            return ProductionReadinessSealDecisionV415(True, "PRODUCTION_READINESS_SEAL_VERIFIED", event_id, bundle_id, crypto_gate_id, critical_readiness_id, "VERIFIED")
        except PromotionCryptoGateErrorV414 as exc:
            raise ProductionReadinessSealErrorV415(str(exc)) from exc

    def get(self, seal_id: str):
        return self.store.get(f"production-readiness-seal-v415:{seal_id}")

    def assert_valid(self, seal_id: str) -> None:
        event = self.get(seal_id)
        if event is None or event.event_type != self.EVENT_TYPE or event.payload.get("status") != "VERIFIED":
            raise ProductionReadinessSealErrorV415("READINESS_SEAL_NOT_VALID")
        payload = dict(event.payload)
        fingerprint = payload.pop("fingerprint", None)
        if fingerprint != _hash(payload):
            raise ProductionReadinessSealErrorV415("READINESS_SEAL_FINGERPRINT_MISMATCH")
        self.crypto_gate.assert_valid(str(payload["crypto_gate_id"]))

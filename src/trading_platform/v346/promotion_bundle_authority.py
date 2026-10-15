from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationLedger,
)


class PromotionBundleAuthorityError(RuntimeError):
    pass


class PromotionBundleAuthorityInvalid(PromotionBundleAuthorityError):
    pass


class PromotionBundleAuthorityConflict(PromotionBundleAuthorityError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _bundle_payload(bundle: PromotionBundle) -> dict[str, Any]:
    bundle.validate()
    if bundle.created_at.tzinfo is None:
        raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_TIMEZONE_REQUIRED")
    return {
        "bundle_id": bundle.bundle_id,
        "strategy_version": bundle.strategy_version,
        "model_version": bundle.model_version,
        "feature_version": bundle.feature_version,
        "target_version": bundle.target_version,
        "configuration_version": bundle.configuration_version,
        "execution_model_version": bundle.execution_model_version,
        "code_version": bundle.code_version,
        "evidence_snapshot_id": bundle.evidence_snapshot_id,
        "gate_results": list(bundle.gate_results),
        "artifact_hashes": list(bundle.artifact_hashes),
        "approval_id": bundle.approval_id,
        "scope": dict(bundle.scope),
        "rollback_target": bundle.rollback_target,
        "content_hash": bundle.content_hash,
        "created_at": bundle.created_at.astimezone(timezone.utc).isoformat(),
    }


def promotion_bundle_fingerprint(bundle: PromotionBundle) -> str:
    """Canonical fingerprint of the exact immutable PromotionBundle contents."""
    return _hash(_bundle_payload(bundle))


def _dependencies(bundle: PromotionBundle) -> tuple[str, ...]:
    return (
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
        _hash(bundle.scope),
    )


@dataclass(frozen=True)
class PromotionBundleAuthorization:
    authorization_id: str
    bundle_id: str
    model_version: str
    bundle_fingerprint: str
    created_at: datetime
    valid_from: datetime
    expires_at: datetime
    reviewer: str
    recorded_at_ms: int
    dependency_checkpoint_sequence: int
    dependency_keys: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return _hash({
            "authorization_id": self.authorization_id,
            "bundle_id": self.bundle_id,
            "model_version": self.model_version,
            "bundle_fingerprint": self.bundle_fingerprint,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
            "dependency_keys": list(self.dependency_keys),
        })


class PromotionBundleAuthorityLedger:
    """Durable authority proving that one exact PromotionBundle was validated for promotion."""

    EVENT_TYPE = "PROMOTION_BUNDLE_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _window(valid_from: datetime, expires_at: datetime) -> tuple[datetime, datetime]:
        if valid_from.tzinfo is None or expires_at.tzinfo is None:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_TIMEZONE_REQUIRED")
        start = valid_from.astimezone(timezone.utc)
        end = expires_at.astimezone(timezone.utc)
        if end <= start:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_WINDOW_INVALID")
        return start, end

    @classmethod
    def authorize(
        cls,
        *,
        authorization_id: str,
        bundle: PromotionBundle,
        valid_from: datetime,
        expires_at: datetime,
        reviewer: str,
        recorded_at_ms: int,
        dependency_authority: DependencyInvalidationLedger,
        store: EventStore | None = None,
    ) -> tuple[PromotionBundleAuthorization, bool]:
        if not authorization_id or not reviewer:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_IDENTIFIERS_REQUIRED")
        if recorded_at_ms < 0:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_TIMESTAMP_INVALID")
        start, end = cls._window(valid_from, expires_at)
        payload_bundle = _bundle_payload(bundle)
        fingerprint = promotion_bundle_fingerprint(bundle)
        if not dependency_authority.store.verify_chain():
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_EVENT_CHAIN_INVALID")
        store = store or dependency_authority.store
        if store is not dependency_authority.store:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORITY_STORE_MISMATCH")

        event_id = f"promotion-bundle:authorize:{authorization_id}"
        existing = store.get(event_id)
        if existing is not None:
            if existing.event_type != cls.EVENT_TYPE:
                raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_EVENT_TYPE_CONFLICT")
            restored = cls._from_event(existing)
            if restored.bundle_fingerprint != fingerprint or restored.bundle_id != bundle.bundle_id:
                raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_AUTHORIZATION_ID_CONFLICT")
            try:
                dependency_authority.assert_unchanged_since(
                    restored.dependency_checkpoint_sequence,
                    _dependencies(bundle),
                )
            except DependencyInvalidationBlocked as exc:
                raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_STALE_AFTER_INVALIDATION") from exc
            return restored, False

        try:
            dependency_authority.assert_clear(_dependencies(bundle))
        except DependencyInvalidationBlocked as exc:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_DEPENDENCY_BLOCKED") from exc
        checkpoint = dependency_authority.checkpoint()
        record = PromotionBundleAuthorization(
            authorization_id=authorization_id,
            bundle_id=bundle.bundle_id,
            model_version=bundle.model_version,
            bundle_fingerprint=fingerprint,
            created_at=bundle.created_at.astimezone(timezone.utc),
            valid_from=start,
            expires_at=end,
            reviewer=reviewer,
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=checkpoint,
            dependency_keys=_dependencies(bundle),
        )
        payload = {
            **{
                "authorization_id": record.authorization_id,
                "bundle_id": record.bundle_id,
                "model_version": record.model_version,
                "bundle_fingerprint": record.bundle_fingerprint,
                "created_at": record.created_at.isoformat(),
                "valid_from": record.valid_from.isoformat(),
                "expires_at": record.expires_at.isoformat(),
                "reviewer": record.reviewer,
                "recorded_at_ms": record.recorded_at_ms,
                "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
                "dependency_keys": list(record.dependency_keys),
            },
            "bundle": payload_bundle,
        }
        existing = store.get(event_id)
        if existing is not None:
            restored = cls._from_event(existing)
            if existing.event_type != cls.EVENT_TYPE or restored.bundle_fingerprint != fingerprint:
                raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_AUTHORIZATION_ID_CONFLICT")
            return restored, False
        try:
            result = store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=cls.EVENT_TYPE,
                aggregate_id=bundle.bundle_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            concurrent = store.get(event_id)
            if concurrent is None:
                raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_CONCURRENT_APPEND_UNRESOLVED") from exc
            restored = cls._from_event(concurrent)
            if restored.bundle_fingerprint != fingerprint:
                raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_CONCURRENT_CONFLICT") from exc
            return restored, False
        if not store.verify_chain():
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_EVENT_CHAIN_INVALID_AFTER_APPEND")
        try:
            dependency_authority.assert_unchanged_since(checkpoint, _dependencies(bundle))
        except DependencyInvalidationBlocked as exc:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_STALE_AFTER_INVALIDATION") from exc
        return cls._from_event(result.event), not result.duplicate

    @staticmethod
    def _from_event(event) -> PromotionBundleAuthorization:
        payload = dict(event.payload)
        return PromotionBundleAuthorization(
            authorization_id=str(payload["authorization_id"]),
            bundle_id=str(payload["bundle_id"]),
            model_version=str(payload["model_version"]),
            bundle_fingerprint=str(payload["bundle_fingerprint"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            valid_from=datetime.fromisoformat(str(payload["valid_from"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            reviewer=str(payload["reviewer"]),
            recorded_at_ms=int(payload["recorded_at_ms"]),
            dependency_checkpoint_sequence=int(payload.get("dependency_checkpoint_sequence", max(0, event.sequence - 1))),
            dependency_keys=tuple(str(v) for v in payload.get("dependency_keys", ())),
        )

    def get(self, authorization_id: str) -> PromotionBundleAuthorization | None:
        if not self.store.verify_chain():
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_EVENT_CHAIN_INVALID")
        event = self.store.get(f"promotion-bundle:authorize:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.EVENT_TYPE:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_EVENT_TYPE_MISMATCH")
        record = self._from_event(event)
        if record.authorization_id != authorization_id:
            raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_AUTHORIZATION_ID_MISMATCH")
        return record

    def _assert_common(
        self,
        record: PromotionBundleAuthorization,
        *,
        bundle: PromotionBundle,
        now: datetime,
        dependency_authority: DependencyInvalidationLedger,
    ) -> PromotionBundleAuthorization:
        if now.tzinfo is None:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_NOW_TIMEZONE_REQUIRED")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORIZATION_EXPIRED")
        try:
            bundle.validate()
        except ValueError as exc:
            raise PromotionBundleAuthorityInvalid(f"PROMOTION_BUNDLE_INVALID:{exc}") from exc
        if record.bundle_id != bundle.bundle_id or record.model_version != bundle.model_version:
            raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_BINDING_MISMATCH")
        if record.bundle_fingerprint != promotion_bundle_fingerprint(bundle):
            raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_FINGERPRINT_MISMATCH")
        keys = record.dependency_keys or _dependencies(bundle)
        if tuple(keys) != tuple(_dependencies(bundle)):
            raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_DEPENDENCY_BINDING_MISMATCH")
        try:
            dependency_authority.assert_clear(keys)
            dependency_authority.assert_unchanged_since(record.dependency_checkpoint_sequence, keys)
        except DependencyInvalidationBlocked as exc:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_STALE_AFTER_INVALIDATION") from exc
        return record

    def assert_valid(
        self,
        authorization_id: str,
        *,
        bundle: PromotionBundle,
        now: datetime,
        dependency_authority: DependencyInvalidationLedger,
    ) -> PromotionBundleAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORIZATION_NOT_FOUND")
        return self._assert_common(record, bundle=bundle, now=now, dependency_authority=dependency_authority)

    def assert_valid_binding(
        self,
        authorization_id: str,
        *,
        bundle_id: str,
        model_version: str,
        now: datetime,
        dependency_authority: DependencyInvalidationLedger,
    ) -> PromotionBundleAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORIZATION_NOT_FOUND")
        if now.tzinfo is None:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_NOW_TIMEZONE_REQUIRED")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_AUTHORIZATION_EXPIRED")
        if (record.bundle_id, record.model_version) != (bundle_id, model_version):
            raise PromotionBundleAuthorityConflict("PROMOTION_BUNDLE_BINDING_MISMATCH")
        keys = record.dependency_keys
        if not keys:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_DEPENDENCY_BINDING_MISSING")
        try:
            dependency_authority.assert_clear(keys)
            dependency_authority.assert_unchanged_since(record.dependency_checkpoint_sequence, keys)
        except DependencyInvalidationBlocked as exc:
            raise PromotionBundleAuthorityInvalid("PROMOTION_BUNDLE_STALE_AFTER_INVALIDATION") from exc
        return record

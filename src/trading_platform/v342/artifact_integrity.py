from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked


class ArtifactIntegrityAuthorityError(RuntimeError):
    pass


class ArtifactIntegrityAuthorityInvalid(ArtifactIntegrityAuthorityError):
    pass


class ArtifactIntegrityAuthorityConflict(ArtifactIntegrityAuthorityError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class ArtifactIntegrityAuthorization:
    authorization_id: str
    artifact_id: str
    artifact_hashes: tuple[str, ...]
    observed_artifact_hashes: tuple[str, ...]
    manifest_hash: str
    signature_verified: bool
    valid_from: datetime
    expires_at: datetime
    reviewer: str
    recorded_at_ms: int
    dependency_checkpoint_sequence: int = 0

    @property
    def fingerprint(self) -> str:
        return _hash({
            "authorization_id": self.authorization_id,
            "artifact_id": self.artifact_id,
            "artifact_hashes": list(self.artifact_hashes),
            "observed_artifact_hashes": list(self.observed_artifact_hashes),
            "manifest_hash": self.manifest_hash,
            "signature_verified": self.signature_verified,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
        })


class ArtifactIntegrityAuthorityLedger:
    """Durable fail-closed authority proving a deployment artifact is intact.

    Integrity is bound to the exact artifact identity and expected hash set. A
    boolean `artifacts_integrity=True` cannot cross the deployment boundary
    without this durable authorization.
    """

    AUTHORIZED_EVENT = "ARTIFACT_INTEGRITY_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ArtifactIntegrityAuthorityInvalid(f"ARTIFACT_INTEGRITY_{field}_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _payload_from_record(cls, record: ArtifactIntegrityAuthorization) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "artifact_id": record.artifact_id,
            "artifact_hashes": list(record.artifact_hashes),
            "observed_artifact_hashes": list(record.observed_artifact_hashes),
            "manifest_hash": record.manifest_hash,
            "signature_verified": record.signature_verified,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "reviewer": record.reviewer,
            "recorded_at_ms": record.recorded_at_ms,
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
        }

    @classmethod
    def _from_event(cls, event) -> ArtifactIntegrityAuthorization:
        p = event.payload
        try:
            record = ArtifactIntegrityAuthorization(
                authorization_id=str(p["authorization_id"]),
                artifact_id=str(p["artifact_id"]),
                artifact_hashes=tuple(str(v) for v in p["artifact_hashes"]),
                observed_artifact_hashes=tuple(str(v) for v in p["observed_artifact_hashes"]),
                manifest_hash=str(p["manifest_hash"]),
                signature_verified=bool(p["signature_verified"]),
                valid_from=datetime.fromisoformat(str(p["valid_from"])),
                expires_at=datetime.fromisoformat(str(p["expires_at"])),
                reviewer=str(p["reviewer"]),
                recorded_at_ms=int(p["recorded_at_ms"]),
                dependency_checkpoint_sequence=int(p.get("dependency_checkpoint_sequence", max(0, int(event.sequence) - 1))),
            )
        except Exception as exc:
            raise ArtifactIntegrityAuthorityInvalid("INVALID_ARTIFACT_INTEGRITY_AUTHORIZATION_PAYLOAD") from exc
        if not all((
            record.authorization_id,
            record.artifact_id,
            record.artifact_hashes,
            record.observed_artifact_hashes,
            record.manifest_hash,
            record.reviewer,
        )):
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_FIELDS_REQUIRED")
        if record.valid_from.tzinfo is None or record.expires_at.tzinfo is None:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_TIMEZONE_REQUIRED")
        if record.expires_at <= record.valid_from:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_WINDOW_INVALID")
        if record.recorded_at_ms < 0:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_TIMESTAMP_INVALID")
        if not record.signature_verified:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_SIGNATURE_NOT_VERIFIED")
        if record.artifact_hashes != record.observed_artifact_hashes:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_HASH_OBSERVATION_MISMATCH")
        return record

    def authorize(
        self,
        *,
        authorization_id: str,
        artifact_id: str,
        artifact_hashes: tuple[str, ...],
        observed_artifact_hashes: tuple[str, ...],
        manifest_hash: str,
        signature_verified: bool,
        valid_from: datetime,
        expires_at: datetime,
        reviewer: str,
        recorded_at_ms: int,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> tuple[ArtifactIntegrityAuthorization, bool]:
        if not authorization_id or not artifact_id or not reviewer:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_IDENTIFIERS_REQUIRED")
        if not artifact_hashes or any(not str(v) for v in artifact_hashes):
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_HASHES_REQUIRED")
        if not observed_artifact_hashes or any(not str(v) for v in observed_artifact_hashes):
            raise ArtifactIntegrityAuthorityInvalid("OBSERVED_ARTIFACT_HASHES_REQUIRED")
        expected = tuple(sorted(set(str(v) for v in artifact_hashes)))
        observed = tuple(sorted(set(str(v) for v in observed_artifact_hashes)))
        if expected != observed:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_HASH_OBSERVATION_MISMATCH")
        if not manifest_hash:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_MANIFEST_HASH_REQUIRED")
        if not signature_verified:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_SIGNATURE_NOT_VERIFIED")
        if valid_from.tzinfo is None or expires_at.tzinfo is None or expires_at <= valid_from:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_WINDOW_INVALID")
        if recorded_at_ms < 0:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_TIMESTAMP_INVALID")
        if not self.store.verify_chain():
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_EVENT_CHAIN_INVALID")
        if dependency_authority is not None:
            event_id = f"artifact-integrity:authorize:{authorization_id}"
            existing = self.store.get(event_id)
            if existing is not None:
                if existing.event_type != self.AUTHORIZED_EVENT:
                    raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_EVENT_TYPE_CONFLICT")
                restored = self._from_event(existing)
                try:
                    dependency_authority.assert_unchanged_since(
                        restored.dependency_checkpoint_sequence,
                        (restored.artifact_id, *restored.artifact_hashes, restored.manifest_hash),
                    )
                except DependencyInvalidationBlocked as exc:
                    raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_STALE_AFTER_INVALIDATION") from exc
                return restored, False
            try:
                dependency_authority.assert_clear((artifact_id, *expected, manifest_hash))
            except DependencyInvalidationBlocked as exc:
                raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_DEPENDENCY_INVALIDATED") from exc
            dependency_checkpoint_sequence = dependency_authority.checkpoint()
        else:
            dependency_checkpoint_sequence = 0

        record = ArtifactIntegrityAuthorization(
            authorization_id=authorization_id,
            artifact_id=artifact_id,
            artifact_hashes=expected,
            observed_artifact_hashes=observed,
            manifest_hash=manifest_hash,
            signature_verified=True,
            valid_from=valid_from.astimezone(timezone.utc),
            expires_at=expires_at.astimezone(timezone.utc),
            reviewer=reviewer,
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=dependency_checkpoint_sequence,
        )
        payload = self._payload_from_record(record)
        event_id = f"artifact-integrity:authorize:{authorization_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.AUTHORIZED_EVENT or _hash(existing.payload) != _hash(payload):
                raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_AUTHORIZATION_ID_CONFLICT")
            return self._from_event(existing), False
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=self.AUTHORIZED_EVENT,
                aggregate_id=artifact_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = self.store.get(event_id)
            if existing is None:
                raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_CONCURRENT_APPEND_UNRESOLVED") from exc
            if _hash(existing.payload) != _hash(payload):
                raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_CONCURRENT_CONFLICT") from exc
            return self._from_event(existing), False
        if not self.store.verify_chain():
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_EVENT_CHAIN_INVALID_AFTER_APPEND")
        if dependency_authority is not None:
            try:
                dependency_authority.assert_unchanged_since(
                    record.dependency_checkpoint_sequence,
                    (record.artifact_id, *record.artifact_hashes, record.manifest_hash),
                )
            except DependencyInvalidationBlocked as exc:
                raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_STALE_AFTER_INVALIDATION") from exc
        return self._from_event(result.event), not result.duplicate

    def get(self, authorization_id: str) -> ArtifactIntegrityAuthorization | None:
        if not self.store.verify_chain():
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_EVENT_CHAIN_INVALID")
        event = self.store.get(f"artifact-integrity:authorize:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.AUTHORIZED_EVENT:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_EVENT_TYPE_MISMATCH")
        record = self._from_event(event)
        if record.authorization_id != authorization_id:
            raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_AUTHORIZATION_ID_MISMATCH")
        return record

    def assert_valid(
        self,
        authorization_id: str,
        *,
        now: datetime,
        artifact_id: str,
        artifact_hashes: tuple[str, ...],
        manifest_hash: str | None = None,
        observed_artifact_hashes: tuple[str, ...] | None = None,
        signature_verified: bool = True,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> ArtifactIntegrityAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_NOT_FOUND")
        if now.tzinfo is None:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_NOW_TIMEZONE_REQUIRED")
        now = now.astimezone(timezone.utc)
        if now < record.valid_from or now >= record.expires_at:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_AUTHORIZATION_EXPIRED")
        if record.artifact_id != artifact_id:
            raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_ARTIFACT_ID_MISMATCH")
        expected_hashes = tuple(sorted(set(str(v) for v in artifact_hashes)))
        if record.artifact_hashes != expected_hashes:
            raise ArtifactIntegrityAuthorityConflict("ARTIFACT_INTEGRITY_HASH_MISMATCH")
        if not signature_verified:
            raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_SIGNATURE_NOT_VERIFIED")
        if manifest_hash is not None and record.manifest_hash != manifest_hash:
            raise ArtifactIntegrityAuthorityConflict("ARTIFACT_MANIFEST_HASH_MISMATCH")
        if observed_artifact_hashes is not None:
            observed = tuple(sorted(set(str(v) for v in observed_artifact_hashes)))
            if record.observed_artifact_hashes != observed:
                raise ArtifactIntegrityAuthorityConflict("ARTIFACT_OBSERVED_HASH_MISMATCH")
        if dependency_authority is not None:
            try:
                dependency_authority.assert_clear((record.artifact_id, *record.artifact_hashes, record.manifest_hash))
            except DependencyInvalidationBlocked as exc:
                raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_DEPENDENCY_INVALIDATED") from exc
            try:
                dependency_authority.assert_unchanged_since(
                    record.dependency_checkpoint_sequence,
                    (record.artifact_id, *record.artifact_hashes, record.manifest_hash),
                )
            except DependencyInvalidationBlocked as exc:
                raise ArtifactIntegrityAuthorityInvalid("ARTIFACT_INTEGRITY_STALE_AFTER_INVALIDATION") from exc
        
        return record

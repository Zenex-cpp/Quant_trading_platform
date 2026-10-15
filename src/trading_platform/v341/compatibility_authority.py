from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.promotion.compatibility import Compatibility, CompatibilityReport
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked


class CompatibilityAuthorityError(RuntimeError):
    pass


class CompatibilityAuthorityInvalid(CompatibilityAuthorityError):
    pass


class CompatibilityAuthorityConflict(CompatibilityAuthorityError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class CompatibilityAuthorization:
    authorization_id: str
    artifact_id: str
    artifact_hashes: tuple[str, ...]
    code_version: str
    configuration_version: str
    execution_model_version: str
    report_fingerprint: str
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
            "code_version": self.code_version,
            "configuration_version": self.configuration_version,
            "execution_model_version": self.execution_model_version,
            "report_fingerprint": self.report_fingerprint,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
        })


class CompatibilityAuthorityLedger:
    """Durable fail-closed authority for artifact/runtime compatibility.

    A compatibility boolean is not an execution credential. Only this durable,
    artifact-bound authorization may cross the deployment execution boundary.
    """

    AUTHORIZED_EVENT = "ARTIFACT_COMPATIBILITY_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise CompatibilityAuthorityInvalid(f"COMPATIBILITY_{field}_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _payload_from_record(cls, record: CompatibilityAuthorization) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "artifact_id": record.artifact_id,
            "artifact_hashes": list(record.artifact_hashes),
            "code_version": record.code_version,
            "configuration_version": record.configuration_version,
            "execution_model_version": record.execution_model_version,
            "report_fingerprint": record.report_fingerprint,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "reviewer": record.reviewer,
            "recorded_at_ms": record.recorded_at_ms,
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
        }

    @classmethod
    def _from_event(cls, event) -> CompatibilityAuthorization:
        p = event.payload
        try:
            record = CompatibilityAuthorization(
                authorization_id=str(p["authorization_id"]),
                artifact_id=str(p["artifact_id"]),
                artifact_hashes=tuple(str(v) for v in p["artifact_hashes"]),
                code_version=str(p["code_version"]),
                configuration_version=str(p["configuration_version"]),
                execution_model_version=str(p["execution_model_version"]),
                report_fingerprint=str(p["report_fingerprint"]),
                valid_from=datetime.fromisoformat(str(p["valid_from"])),
                expires_at=datetime.fromisoformat(str(p["expires_at"])),
                reviewer=str(p["reviewer"]),
                recorded_at_ms=int(p["recorded_at_ms"]),
                dependency_checkpoint_sequence=int(p.get("dependency_checkpoint_sequence", max(0, int(event.sequence) - 1))),
            )
        except Exception as exc:
            raise CompatibilityAuthorityInvalid("INVALID_COMPATIBILITY_AUTHORIZATION_PAYLOAD") from exc
        if not all((
            record.authorization_id, record.artifact_id, record.artifact_hashes,
            record.code_version, record.configuration_version, record.execution_model_version,
            record.report_fingerprint, record.reviewer,
        )):
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_FIELDS_REQUIRED")
        if record.valid_from.tzinfo is None or record.expires_at.tzinfo is None:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_TIMEZONE_REQUIRED")
        if record.expires_at <= record.valid_from:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_WINDOW_INVALID")
        if record.recorded_at_ms < 0:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_TIMESTAMP_INVALID")
        return record

    def authorize(
        self,
        *,
        authorization_id: str,
        artifact_id: str,
        artifact_hashes: tuple[str, ...],
        code_version: str,
        configuration_version: str,
        execution_model_version: str,
        report: CompatibilityReport,
        valid_from: datetime,
        expires_at: datetime,
        reviewer: str,
        recorded_at_ms: int,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> tuple[CompatibilityAuthorization, bool]:
        if not authorization_id or not artifact_id or not reviewer:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_IDENTIFIERS_REQUIRED")
        if not artifact_hashes or any(not str(v) for v in artifact_hashes):
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_ARTIFACT_HASHES_REQUIRED")
        if not code_version or not configuration_version or not execution_model_version:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_VERSION_BINDING_REQUIRED")
        if report.overall() is not Compatibility.COMPATIBLE:
            raise CompatibilityAuthorityInvalid(f"ARTIFACT_COMPATIBILITY_{report.overall().value}")
        if valid_from.tzinfo is None or expires_at.tzinfo is None or expires_at <= valid_from:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_WINDOW_INVALID")
        if recorded_at_ms < 0:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_TIMESTAMP_INVALID")
        if not self.store.verify_chain():
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_EVENT_CHAIN_INVALID")
        if dependency_authority is not None:
            event_id = f"artifact-compatibility:authorize:{authorization_id}"
            existing = self.store.get(event_id)
            if existing is not None:
                if existing.event_type != self.AUTHORIZED_EVENT:
                    raise CompatibilityAuthorityConflict("COMPATIBILITY_EVENT_TYPE_CONFLICT")
                restored = self._from_event(existing)
                try:
                    dependency_authority.assert_unchanged_since(
                        restored.dependency_checkpoint_sequence,
                        (restored.artifact_id, *restored.artifact_hashes, restored.code_version, restored.configuration_version, restored.execution_model_version),
                    )
                except DependencyInvalidationBlocked as exc:
                    raise CompatibilityAuthorityInvalid("COMPATIBILITY_STALE_AFTER_INVALIDATION") from exc
                return restored, False
            try:
                dependency_authority.assert_clear((artifact_id, *artifact_hashes, code_version, configuration_version, execution_model_version))
            except DependencyInvalidationBlocked as exc:
                raise CompatibilityAuthorityInvalid("COMPATIBILITY_DEPENDENCY_INVALIDATED") from exc
            dependency_checkpoint_sequence = dependency_authority.checkpoint()
        else:
            dependency_checkpoint_sequence = 0

        record = CompatibilityAuthorization(
            authorization_id=authorization_id,
            artifact_id=artifact_id,
            artifact_hashes=tuple(sorted(set(str(v) for v in artifact_hashes))),
            code_version=code_version,
            configuration_version=configuration_version,
            execution_model_version=execution_model_version,
            report_fingerprint=report.fingerprint,
            valid_from=valid_from.astimezone(timezone.utc),
            expires_at=expires_at.astimezone(timezone.utc),
            reviewer=reviewer,
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=dependency_checkpoint_sequence,
        )
        payload = self._payload_from_record(record)
        event_id = f"artifact-compatibility:authorize:{authorization_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.AUTHORIZED_EVENT or _hash(existing.payload) != _hash(payload):
                raise CompatibilityAuthorityConflict("COMPATIBILITY_AUTHORIZATION_ID_CONFLICT")
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
                raise CompatibilityAuthorityInvalid("COMPATIBILITY_CONCURRENT_APPEND_UNRESOLVED") from exc
            if _hash(existing.payload) != _hash(payload):
                raise CompatibilityAuthorityConflict("COMPATIBILITY_CONCURRENT_CONFLICT") from exc
            return self._from_event(existing), False
        if not self.store.verify_chain():
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_EVENT_CHAIN_INVALID_AFTER_APPEND")
        if dependency_authority is not None:
            try:
                dependency_authority.assert_unchanged_since(
                    record.dependency_checkpoint_sequence,
                    (record.artifact_id, *record.artifact_hashes, record.code_version, record.configuration_version, record.execution_model_version),
                )
            except DependencyInvalidationBlocked as exc:
                raise CompatibilityAuthorityInvalid("COMPATIBILITY_STALE_AFTER_INVALIDATION") from exc
        return self._from_event(result.event), not result.duplicate

    def get(self, authorization_id: str) -> CompatibilityAuthorization | None:
        if not self.store.verify_chain():
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_EVENT_CHAIN_INVALID")
        event = self.store.get(f"artifact-compatibility:authorize:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.AUTHORIZED_EVENT:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_EVENT_TYPE_MISMATCH")
        record = self._from_event(event)
        if record.authorization_id != authorization_id:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_AUTHORIZATION_ID_MISMATCH")
        return record

    def assert_valid(
        self,
        authorization_id: str,
        *,
        now: datetime,
        artifact_id: str,
        artifact_hashes: tuple[str, ...],
        code_version: str,
        configuration_version: str,
        execution_model_version: str,
        report: CompatibilityReport | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> CompatibilityAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_NOT_FOUND")
        if now.tzinfo is None:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_NOW_TIMEZONE_REQUIRED")
        now = now.astimezone(timezone.utc)
        if now < record.valid_from or now >= record.expires_at:
            raise CompatibilityAuthorityInvalid("COMPATIBILITY_AUTHORIZATION_EXPIRED")
        if record.artifact_id != artifact_id:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_ARTIFACT_ID_MISMATCH")
        expected_hashes = tuple(sorted(set(str(v) for v in artifact_hashes)))
        if record.artifact_hashes != expected_hashes:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_ARTIFACT_HASH_MISMATCH")
        if record.code_version != code_version:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_CODE_VERSION_MISMATCH")
        if record.configuration_version != configuration_version:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_CONFIGURATION_VERSION_MISMATCH")
        if record.execution_model_version != execution_model_version:
            raise CompatibilityAuthorityConflict("COMPATIBILITY_EXECUTION_MODEL_VERSION_MISMATCH")
        if report is not None:
            if report.overall() is not Compatibility.COMPATIBLE:
                raise CompatibilityAuthorityInvalid(f"ARTIFACT_COMPATIBILITY_{report.overall().value}")
            if report.fingerprint != record.report_fingerprint:
                raise CompatibilityAuthorityConflict("COMPATIBILITY_REPORT_FINGERPRINT_MISMATCH")
        if dependency_authority is not None:
            try:
                dependency_authority.assert_clear((record.artifact_id, *record.artifact_hashes, record.code_version, record.configuration_version, record.execution_model_version))
            except DependencyInvalidationBlocked as exc:
                raise CompatibilityAuthorityInvalid("COMPATIBILITY_DEPENDENCY_INVALIDATED") from exc
            try:
                dependency_authority.assert_unchanged_since(
                    record.dependency_checkpoint_sequence,
                    (record.artifact_id, *record.artifact_hashes, record.code_version, record.configuration_version, record.execution_model_version),
                )
            except DependencyInvalidationBlocked as exc:
                raise CompatibilityAuthorityInvalid("COMPATIBILITY_STALE_AFTER_INVALIDATION") from exc
        return record

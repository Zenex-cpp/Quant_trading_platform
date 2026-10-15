from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.evidence.snapshot import EvidenceSnapshot, snapshot_content_hash
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationBlocked, DependencyInvalidationLedger


class EvidenceSnapshotAuthorityError(RuntimeError):
    pass


class EvidenceSnapshotAuthorityInvalid(EvidenceSnapshotAuthorityError):
    pass


class EvidenceSnapshotAuthorityConflict(EvidenceSnapshotAuthorityError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class EvidenceSnapshotAuthorization:
    authorization_id: str
    snapshot_id: str
    promotion_id: str
    bundle_id: str
    model_version: str
    evidence_ids: tuple[str, ...]
    metrics_hash: str
    metrics: object
    gates: tuple[str, ...]
    dependencies: tuple[str, ...]
    versions: tuple[str, ...]
    hashes: tuple[str, ...]
    methodology: tuple[str, ...]
    approvals: tuple[str, ...]
    scope: dict[str, str]
    content_hash: str
    valid_from: datetime
    expires_at: datetime
    reviewer: str
    recorded_at_ms: int
    dependency_checkpoint_sequence: int = 0

    @property
    def fingerprint(self) -> str:
        return _hash({
            "authorization_id": self.authorization_id,
            "snapshot_id": self.snapshot_id,
            "promotion_id": self.promotion_id,
            "bundle_id": self.bundle_id,
            "model_version": self.model_version,
            "evidence_ids": list(self.evidence_ids),
            "metrics_hash": self.metrics_hash,
            "metrics": self.metrics,
            "gates": list(self.gates),
            "dependencies": list(self.dependencies),
            "versions": list(self.versions),
            "hashes": list(self.hashes),
            "methodology": list(self.methodology),
            "approvals": list(self.approvals),
            "scope": dict(self.scope),
            "content_hash": self.content_hash,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
        })


class EvidenceSnapshotAuthorityLedger:
    """Durable authorization proving an immutable evidence snapshot exists for a promotion.

    The promotion boundary never trusts a live evidence reference alone. The exact
    snapshot, its content hash, promotion binding, scope and dependency checkpoint
    are persisted in the EventStore and revalidated before every promotion.
    """

    AUTHORIZED_EVENT = "EVIDENCE_SNAPSHOT_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise EvidenceSnapshotAuthorityInvalid(f"EVIDENCE_SNAPSHOT_{field}_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _payload_from_record(cls, record: EvidenceSnapshotAuthorization) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "snapshot_id": record.snapshot_id,
            "promotion_id": record.promotion_id,
            "bundle_id": record.bundle_id,
            "model_version": record.model_version,
            "evidence_ids": list(record.evidence_ids),
            "metrics_hash": record.metrics_hash,
            "metrics": record.metrics,
            "gates": list(record.gates),
            "dependencies": list(record.dependencies),
            "versions": list(record.versions),
            "hashes": list(record.hashes),
            "methodology": list(record.methodology),
            "approvals": list(record.approvals),
            "scope": dict(record.scope),
            "content_hash": record.content_hash,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "reviewer": record.reviewer,
            "recorded_at_ms": record.recorded_at_ms,
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
        }

    @classmethod
    def _from_event(cls, event) -> EvidenceSnapshotAuthorization:
        p = event.payload
        try:
            record = EvidenceSnapshotAuthorization(
                authorization_id=str(p["authorization_id"]),
                snapshot_id=str(p["snapshot_id"]),
                promotion_id=str(p["promotion_id"]),
                bundle_id=str(p["bundle_id"]),
                model_version=str(p["model_version"]),
                evidence_ids=tuple(str(v) for v in p["evidence_ids"]),
                metrics_hash=str(p["metrics_hash"]),
                metrics=p.get("metrics"),
                gates=tuple(str(v) for v in p["gates"]),
                dependencies=tuple(str(v) for v in p["dependencies"]),
                versions=tuple(str(v) for v in p["versions"]),
                hashes=tuple(str(v) for v in p["hashes"]),
                methodology=tuple(str(v) for v in p["methodology"]),
                approvals=tuple(str(v) for v in p["approvals"]),
                scope={str(k): str(v) for k, v in dict(p["scope"]).items()},
                content_hash=str(p["content_hash"]),
                valid_from=datetime.fromisoformat(str(p["valid_from"])),
                expires_at=datetime.fromisoformat(str(p["expires_at"])),
                reviewer=str(p["reviewer"]),
                recorded_at_ms=int(p["recorded_at_ms"]),
                dependency_checkpoint_sequence=int(p.get("dependency_checkpoint_sequence", max(0, int(event.sequence) - 1))),
            )
        except Exception as exc:
            raise EvidenceSnapshotAuthorityInvalid("INVALID_EVIDENCE_SNAPSHOT_AUTHORIZATION_PAYLOAD") from exc
        cls._validate_record(record)
        return record

    @staticmethod
    def _validate_record(record: EvidenceSnapshotAuthorization) -> None:
        if not all((record.authorization_id, record.snapshot_id, record.promotion_id, record.bundle_id, record.model_version,
                    record.metrics_hash, record.content_hash, record.reviewer)):
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_REQUIRED_FIELDS")
        for name, values in (
            ("evidence_ids", record.evidence_ids), ("gates", record.gates), ("dependencies", record.dependencies),
            ("versions", record.versions), ("hashes", record.hashes), ("methodology", record.methodology),
            ("approvals", record.approvals),
        ):
            if not values or any(not str(v) for v in values):
                raise EvidenceSnapshotAuthorityInvalid(f"EVIDENCE_SNAPSHOT_{name.upper()}_REQUIRED")
        if record.scope is None:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_SCOPE_REQUIRED")
        if record.valid_from.tzinfo is None or record.expires_at.tzinfo is None or record.expires_at <= record.valid_from:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_VALIDITY_WINDOW_INVALID")
        if record.recorded_at_ms < 0 or record.dependency_checkpoint_sequence < 0:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_TIMESTAMP_INVALID")
        snapshot = EvidenceSnapshot(
            snapshot_id=record.snapshot_id,
            evidence_ids=record.evidence_ids,
            metrics_hash=record.metrics_hash,
            gates=record.gates,
            dependencies=record.dependencies,
            versions=record.versions,
            hashes=record.hashes,
            methodology=record.methodology,
            approvals=record.approvals,
            scope=record.scope,
            content_hash=record.content_hash,
            metrics=record.metrics,
        )
        expected_metrics_hash = sha256(json.dumps(record.metrics, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
        if expected_metrics_hash != record.metrics_hash:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_METRICS_HASH_MISMATCH")
        if snapshot_content_hash(snapshot) != record.content_hash:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_CONTENT_HASH_MISMATCH")

    def authorize(
        self,
        *,
        snapshot: EvidenceSnapshot,
        promotion_id: str,
        bundle_id: str,
        model_version: str,
        valid_from: datetime,
        expires_at: datetime,
        reviewer: str,
        recorded_at_ms: int,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> tuple[EvidenceSnapshotAuthorization, bool]:
        if not promotion_id or not bundle_id or not model_version or not reviewer:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_IDENTIFIERS_REQUIRED")
        if not isinstance(snapshot, EvidenceSnapshot):
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_OBJECT_REQUIRED")
        if snapshot_content_hash(snapshot) != snapshot.content_hash:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_CONTENT_HASH_MISMATCH")
        if dependency_authority is not None:
            try:
                dependency_authority.assert_evidence_not_holdout_contaminated(tuple(snapshot.evidence_ids))
            except DependencyInvalidationBlocked as exc:
                raise EvidenceSnapshotAuthorityInvalid("FINAL_HOLDOUT_CONTAMINATED_EVIDENCE") from exc
        self._validate_record(EvidenceSnapshotAuthorization(
            authorization_id=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            promotion_id=promotion_id,
            bundle_id=bundle_id,
            model_version=model_version,
            evidence_ids=tuple(snapshot.evidence_ids),
            metrics_hash=snapshot.metrics_hash,
            metrics=snapshot.metrics,
            gates=tuple(snapshot.gates),
            dependencies=tuple(snapshot.dependencies),
            versions=tuple(snapshot.versions),
            hashes=tuple(snapshot.hashes),
            methodology=tuple(snapshot.methodology),
            approvals=tuple(snapshot.approvals),
            scope=dict(snapshot.scope),
            content_hash=snapshot.content_hash,
            valid_from=valid_from.astimezone(timezone.utc),
            expires_at=expires_at.astimezone(timezone.utc),
            reviewer=reviewer,
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=0,
        ))
        if not self.store.verify_chain():
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_EVENT_CHAIN_INVALID")
        event_id = f"evidence-snapshot:authorize:{snapshot.snapshot_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            restored = self._from_event(existing)
            candidate = EvidenceSnapshotAuthorization(
                authorization_id=snapshot.snapshot_id,
                snapshot_id=snapshot.snapshot_id,
                promotion_id=promotion_id,
                bundle_id=bundle_id,
                model_version=model_version,
                evidence_ids=tuple(snapshot.evidence_ids),
                metrics_hash=snapshot.metrics_hash,
                metrics=snapshot.metrics,
                gates=tuple(snapshot.gates),
                dependencies=tuple(snapshot.dependencies),
                versions=tuple(snapshot.versions),
                hashes=tuple(snapshot.hashes),
                methodology=tuple(snapshot.methodology),
                approvals=tuple(snapshot.approvals),
                scope=dict(snapshot.scope),
                content_hash=snapshot.content_hash,
                valid_from=valid_from.astimezone(timezone.utc),
                expires_at=expires_at.astimezone(timezone.utc),
                reviewer=reviewer,
                recorded_at_ms=recorded_at_ms,
                dependency_checkpoint_sequence=restored.dependency_checkpoint_sequence,
            )
            if restored.fingerprint != candidate.fingerprint:
                raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_AUTHORIZATION_CONFLICT")
            self._assert_dependency_validity(restored, dependency_authority)
            return restored, False
        if recorded_at_ms < 0:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_TIMESTAMP_INVALID")
        dependencies = tuple(sorted(set((bundle_id, promotion_id, model_version, *snapshot.evidence_ids, *snapshot.gates,
                                         *snapshot.dependencies, *snapshot.versions, *snapshot.hashes, *snapshot.approvals))))
        checkpoint = 0
        if dependency_authority is not None:
            try:
                dependency_authority.assert_clear(dependencies)
            except DependencyInvalidationBlocked as exc:
                raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_DEPENDENCY_INVALIDATED") from exc
            checkpoint = dependency_authority.checkpoint()
        record = EvidenceSnapshotAuthorization(
            authorization_id=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            promotion_id=promotion_id,
            bundle_id=bundle_id,
            model_version=model_version,
            evidence_ids=tuple(snapshot.evidence_ids),
            metrics_hash=snapshot.metrics_hash,
            metrics=snapshot.metrics,
            gates=tuple(snapshot.gates),
            dependencies=tuple(snapshot.dependencies),
            versions=tuple(snapshot.versions),
            hashes=tuple(snapshot.hashes),
            methodology=tuple(snapshot.methodology),
            approvals=tuple(snapshot.approvals),
            scope=dict(snapshot.scope),
            content_hash=snapshot.content_hash,
            valid_from=valid_from.astimezone(timezone.utc),
            expires_at=expires_at.astimezone(timezone.utc),
            reviewer=reviewer,
            recorded_at_ms=recorded_at_ms,
            dependency_checkpoint_sequence=checkpoint,
        )
        payload = self._payload_from_record(record)
        appended = self.store.append(event_id=event_id, occurred_at_ms=recorded_at_ms,
                                     event_type=self.AUTHORIZED_EVENT, aggregate_id=record.snapshot_id, payload=payload)
        if not self.store.verify_chain():
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_EVENT_CHAIN_INVALID_AFTER_APPEND")
        return self._from_event(appended.event), not appended.duplicate

    def get(self, authorization_id: str) -> EvidenceSnapshotAuthorization | None:
        if not self.store.verify_chain():
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_EVENT_CHAIN_INVALID")
        event = self.store.get(f"evidence-snapshot:authorize:{authorization_id}")
        return self._from_event(event) if event is not None else None

    def assert_valid(
        self,
        authorization_id: str,
        *,
        now: datetime,
        promotion_id: str,
        bundle_id: str,
        model_version: str,
        required_gate_ids: tuple[str, ...] = (),
        required_artifact_hashes: tuple[str, ...] = (),
        required_versions: tuple[str, ...] = (),
        approval_id: str | None = None,
        requested_scope: Mapping[str, str] | None = None,
        dependency_authority: DependencyInvalidationLedger | None = None,
    ) -> EvidenceSnapshotAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_AUTHORITY_NOT_FOUND")
        if now.tzinfo is None:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_NOW_TIMEZONE_REQUIRED")
        if now < record.valid_from or now >= record.expires_at:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_AUTHORITY_EXPIRED")
        if record.promotion_id != promotion_id:
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_PROMOTION_MISMATCH")
        if record.bundle_id != bundle_id:
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_BUNDLE_MISMATCH")
        if record.model_version != model_version:
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_MODEL_VERSION_MISMATCH")
        if not set(required_gate_ids).issubset(set(record.gates)):
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_GATE_MISMATCH")
        if not set(required_artifact_hashes).issubset(set(record.hashes)):
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_ARTIFACT_HASH_MISMATCH")
        if not set(required_versions).issubset(set(record.versions)):
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_VERSION_MISMATCH")
        if approval_id is not None and approval_id not in record.approvals:
            raise EvidenceSnapshotAuthorityConflict("EVIDENCE_SNAPSHOT_APPROVAL_MISMATCH")
        if requested_scope:
            for key, value in requested_scope.items():
                allowed = record.scope.get(key)
                if allowed not in (None, "*", value):
                    raise EvidenceSnapshotAuthorityConflict(f"EVIDENCE_SNAPSHOT_SCOPE_MISMATCH:{key}")
        self._assert_dependency_validity(record, dependency_authority)
        return record

    def _assert_dependency_validity(self, record: EvidenceSnapshotAuthorization,
                                    dependency_authority: DependencyInvalidationLedger | None) -> None:
        if dependency_authority is None:
            return
        deps = tuple(sorted(set((record.snapshot_id, record.bundle_id, record.promotion_id, record.model_version, *record.evidence_ids,
                                *record.gates, *record.dependencies, *record.versions, *record.hashes, *record.approvals))))
        try:
            dependency_authority.assert_evidence_not_holdout_contaminated(record.evidence_ids)
            dependency_authority.assert_clear(deps)
            dependency_authority.assert_unchanged_since(record.dependency_checkpoint_sequence, deps)
        except DependencyInvalidationBlocked as exc:
            raise EvidenceSnapshotAuthorityInvalid("EVIDENCE_SNAPSHOT_STALE_AFTER_INVALIDATION") from exc

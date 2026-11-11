from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger, DependencyInvalidationBlocked
from trading_platform.v408.gate_promotion import (
    CriticalPromotionGateErrorV408,
    GatePromotionAuthorizationLedgerV408,
)


class ChampionGateAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChampionGateAuthorization:
    authorization_id: str
    model_id: str
    model_version: str
    candidate_id: str
    required_gate_ids: tuple[str, ...]
    passed_gate_ids: tuple[str, ...]
    promotion_id: str
    valid_from: datetime
    expires_at: datetime
    reviewer: str
    recorded_at_ms: int
    dependency_checkpoint_sequence: int = 0
    gate_authorization_ids: tuple[str, ...] = ()
    gate_fingerprints: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        payload = {
            "authorization_id": self.authorization_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "candidate_id": self.candidate_id,
            "required_gate_ids": list(self.required_gate_ids),
            "passed_gate_ids": list(self.passed_gate_ids),
            "promotion_id": self.promotion_id,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "recorded_at_ms": self.recorded_at_ms,
            "dependency_checkpoint_sequence": self.dependency_checkpoint_sequence,
            "gate_authorization_ids": list(self.gate_authorization_ids),
            "gate_fingerprints": list(self.gate_fingerprints),
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ChampionGateAuthorityLedger:
    """Durable, fail-closed authority proving required gates before Champion role."""

    EVENT_TYPE = "CHAMPION_GATE_AUTHORIZED"

    def __init__(self, store: EventStore | None = None):
        self.store = store or EventStore()

    @staticmethod
    def _validate_window(valid_from: datetime, expires_at: datetime) -> None:
        if valid_from.tzinfo is None or expires_at.tzinfo is None:
            raise ChampionGateAuthorityError("CHAMPION_GATE_TIMEZONE_REQUIRED")
        if expires_at <= valid_from:
            raise ChampionGateAuthorityError("CHAMPION_GATE_WINDOW_INVALID")

    @classmethod
    def authorize(
        cls,
        *,
        authorization_id: str,
        model_id: str,
        model_version: str,
        candidate_id: str,
        required_gate_ids: Iterable[str],
        promotion_id: str,
        now: datetime,
        valid_from: datetime,
        expires_at: datetime,
        reviewer: str,
        recorded_at_ms: int,
        dependency_authority: DependencyInvalidationLedger,
        store: EventStore | None = None,
    ) -> tuple[ChampionGateAuthorization, bool]:
        if not all((authorization_id, model_id, model_version, candidate_id, promotion_id, reviewer)):
            raise ChampionGateAuthorityError("CHAMPION_GATE_IDENTIFIERS_REQUIRED")
        required = tuple(dict.fromkeys(required_gate_ids))
        if not required:
            raise ChampionGateAuthorityError("REQUIRED_GATES_REQUIRED")
        if now.tzinfo is None:
            raise ChampionGateAuthorityError("CHAMPION_GATE_NOW_TIMEZONE_REQUIRED")
        if recorded_at_ms < 0:
            raise ChampionGateAuthorityError("CHAMPION_GATE_TIMESTAMP_INVALID")
        cls._validate_window(valid_from, expires_at)
        if not dependency_authority.store.verify_chain():
            raise ChampionGateAuthorityError("DEPENDENCY_EVENT_CHAIN_INVALID")
        store = store or dependency_authority.store
        if store is not dependency_authority.store:
            raise ChampionGateAuthorityError("AUTHORITY_STORE_MISMATCH")
        dependencies = (candidate_id, promotion_id, *required)
        dependency_checkpoint_sequence = dependency_authority.checkpoint()
        gate_ledger = GatePromotionAuthorizationLedgerV408(store)
        gate_records = []
        now_ms = int(now.timestamp() * 1000)
        for gate_id in required:
            try:
                gate_record = gate_ledger.assert_registered_reusable(
                    gate_id, dependency_authority, now_ms,
                )
            except CriticalPromotionGateErrorV408 as exc:
                if "GATE_REUSE_BLOCKED_AFTER_INVALIDATION" in str(exc):
                    raise ChampionGateAuthorityError(
                        "CHAMPION_GATE_DEPENDENCY_BLOCKED"
                    ) from exc
                if "GATE_REUSE_REQUIRES_RERUN" in str(exc):
                    raise ChampionGateAuthorityError(
                        "CHAMPION_GATE_STALE_AFTER_INVALIDATION"
                    ) from exc
                raise ChampionGateAuthorityError(
                    f"REQUIRED_GATE_AUTHORITY_INVALID:{gate_id}"
                ) from exc
            if gate_record.candidate_version != model_version:
                raise ChampionGateAuthorityError(
                    f"REQUIRED_GATE_CANDIDATE_VERSION_MISMATCH:{gate_id}"
                )
            if gate_record.recorded_at_ms > recorded_at_ms:
                raise ChampionGateAuthorityError(
                    f"REQUIRED_GATE_AUTHORITY_AFTER_CHAMPION_AUTHORIZATION:{gate_id}"
                )
            gate_records.append(gate_record)
        passed = required
        gate_authorization_ids = tuple(record.authorization_id for record in gate_records)
        gate_fingerprints = tuple(record.gate_fingerprint for record in gate_records)
        event_id = f"champion-gate:authorize:{authorization_id}"
        existing = store.get(event_id)
        if existing is not None:
            if existing.event_type != cls.EVENT_TYPE:
                raise ChampionGateAuthorityError("AUTHORIZATION_EVENT_TYPE_CONFLICT")
            restored = cls._from_event(existing.payload, existing.sequence)
            if (
                restored.authorization_id != authorization_id
                or restored.model_id != model_id
                or restored.model_version != model_version
                or restored.candidate_id != candidate_id
                or restored.required_gate_ids != required
                or restored.passed_gate_ids != passed
                or restored.promotion_id != promotion_id
                or restored.valid_from != valid_from.astimezone(timezone.utc)
                or restored.expires_at != expires_at.astimezone(timezone.utc)
                or restored.reviewer != reviewer
                or restored.recorded_at_ms != recorded_at_ms
                or restored.gate_authorization_ids != gate_authorization_ids
                or restored.gate_fingerprints != gate_fingerprints
            ):
                raise ChampionGateAuthorityError("CHAMPION_GATE_AUTHORIZATION_ID_CONFLICT")
            try:
                dependency_authority.assert_unchanged_since(
                    restored.dependency_checkpoint_sequence,
                    (restored.candidate_id, restored.promotion_id, *restored.required_gate_ids),
                )
            except DependencyInvalidationBlocked as exc:
                raise ChampionGateAuthorityError("CHAMPION_GATE_STALE_AFTER_INVALIDATION") from exc
            return restored, False
        try:
            dependency_authority.assert_clear(dependencies)
            dependency_authority.assert_unchanged_since(
                dependency_checkpoint_sequence, dependencies,
            )
        except DependencyInvalidationBlocked as exc:
            raise ChampionGateAuthorityError("CHAMPION_GATE_DEPENDENCY_BLOCKED") from exc
        record = ChampionGateAuthorization(
            authorization_id, model_id, model_version, candidate_id, required, passed,
            promotion_id, valid_from.astimezone(timezone.utc), expires_at.astimezone(timezone.utc),
            reviewer, recorded_at_ms, dependency_checkpoint_sequence,
            gate_authorization_ids, gate_fingerprints,
        )
        payload = {
            "authorization_id": record.authorization_id,
            "model_id": record.model_id,
            "model_version": record.model_version,
            "candidate_id": record.candidate_id,
            "required_gate_ids": list(record.required_gate_ids),
            "passed_gate_ids": list(record.passed_gate_ids),
            "promotion_id": record.promotion_id,
            "valid_from": record.valid_from.isoformat(),
            "expires_at": record.expires_at.isoformat(),
            "reviewer": record.reviewer,
            "recorded_at_ms": record.recorded_at_ms,
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
            "gate_authorization_ids": list(record.gate_authorization_ids),
            "gate_fingerprints": list(record.gate_fingerprints),
        }
        result = store.append(
            event_id=event_id, occurred_at_ms=recorded_at_ms,
            event_type=cls.EVENT_TYPE, aggregate_id=model_id, payload=payload,
        )
        if not store.verify_chain():
            raise ChampionGateAuthorityError("EVENT_CHAIN_INVALID_AFTER_AUTHORIZATION")
        try:
            dependency_authority.assert_unchanged_since(
                record.dependency_checkpoint_sequence,
                (record.candidate_id, record.promotion_id, *record.required_gate_ids),
            )
        except DependencyInvalidationBlocked as exc:
            raise ChampionGateAuthorityError("CHAMPION_GATE_STALE_AFTER_INVALIDATION") from exc
        return cls._from_event(result.event.payload, result.event.sequence), not result.duplicate

    @staticmethod
    def _from_event(payload: dict, event_sequence: int | None = None) -> ChampionGateAuthorization:
        checkpoint = int(payload.get("dependency_checkpoint_sequence", max(0, int(event_sequence or 1) - 1)))
        return ChampionGateAuthorization(
            str(payload["authorization_id"]), str(payload["model_id"]), str(payload["model_version"]),
            str(payload["candidate_id"]), tuple(payload["required_gate_ids"]), tuple(payload["passed_gate_ids"]),
            str(payload["promotion_id"]), datetime.fromisoformat(payload["valid_from"]),
            datetime.fromisoformat(payload["expires_at"]), str(payload["reviewer"]), int(payload["recorded_at_ms"]), checkpoint,
            tuple(str(v) for v in payload.get("gate_authorization_ids", ())),
            tuple(str(v) for v in payload.get("gate_fingerprints", ())),
        )

    def get(self, authorization_id: str) -> ChampionGateAuthorization | None:
        if not self.store.verify_chain():
            raise ChampionGateAuthorityError("EVENT_CHAIN_INVALID")
        event = self.store.get(f"champion-gate:authorize:{authorization_id}")
        return None if event is None else self._from_event(event.payload, event.sequence)

    def assert_valid(
        self, authorization_id: str, *, now: datetime, model_id: str, model_version: str,
        candidate_id: str, promotion_id: str, dependency_authority: DependencyInvalidationLedger,
    ) -> ChampionGateAuthorization:
        if now.tzinfo is None:
            raise ChampionGateAuthorityError("CHAMPION_GATE_NOW_TIMEZONE_REQUIRED")
        record = self.get(authorization_id)
        if record is None:
            raise ChampionGateAuthorityError("CHAMPION_GATE_AUTHORIZATION_NOT_FOUND")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise ChampionGateAuthorityError("CHAMPION_GATE_AUTHORIZATION_EXPIRED")
        if (record.model_id, record.model_version, record.candidate_id, record.promotion_id) != (model_id, model_version, candidate_id, promotion_id):
            raise ChampionGateAuthorityError("CHAMPION_GATE_BINDING_MISMATCH")
        if not set(record.required_gate_ids).issubset(record.passed_gate_ids):
            raise ChampionGateAuthorityError("REQUIRED_GATES_NOT_PASSED")
        if (
            record.passed_gate_ids != record.required_gate_ids
            or len(record.gate_authorization_ids) != len(record.required_gate_ids)
            or len(record.gate_fingerprints) != len(record.required_gate_ids)
        ):
            raise ChampionGateAuthorityError("REQUIRED_GATE_AUTHORIZATION_BINDING_MISSING")
        gate_ledger = GatePromotionAuthorizationLedgerV408(dependency_authority.store)
        now_ms = int(now_utc.timestamp() * 1000)
        for gate_id, expected_authorization_id, expected_fingerprint in zip(
            record.required_gate_ids,
            record.gate_authorization_ids,
            record.gate_fingerprints,
        ):
            try:
                gate_record = gate_ledger.assert_registered_reusable(
                    gate_id, dependency_authority, now_ms,
                )
            except CriticalPromotionGateErrorV408 as exc:
                if "GATE_REUSE_BLOCKED_AFTER_INVALIDATION" in str(exc):
                    raise ChampionGateAuthorityError(
                        "CHAMPION_GATE_DEPENDENCY_BLOCKED"
                    ) from exc
                if "GATE_REUSE_REQUIRES_RERUN" in str(exc):
                    raise ChampionGateAuthorityError(
                        "CHAMPION_GATE_STALE_AFTER_INVALIDATION"
                    ) from exc
                raise ChampionGateAuthorityError(
                    f"REQUIRED_GATE_AUTHORITY_INVALID:{gate_id}"
                ) from exc
            if (
                gate_record.authorization_id != expected_authorization_id
                or gate_record.gate_fingerprint != expected_fingerprint
                or gate_record.candidate_version != record.model_version
            ):
                raise ChampionGateAuthorityError(
                    f"REQUIRED_GATE_AUTHORIZATION_CHANGED:{gate_id}"
                )
        try:
            dependency_authority.assert_clear((record.candidate_id, record.promotion_id, *record.required_gate_ids))
        except DependencyInvalidationBlocked as exc:
            raise ChampionGateAuthorityError("CHAMPION_GATE_DEPENDENCY_BLOCKED") from exc
        try:
            dependency_authority.assert_unchanged_since(
                record.dependency_checkpoint_sequence,
                (record.candidate_id, record.promotion_id, *record.required_gate_ids),
            )
        except DependencyInvalidationBlocked as exc:
            raise ChampionGateAuthorityError("CHAMPION_GATE_STALE_AFTER_INVALIDATION") from exc
        return record

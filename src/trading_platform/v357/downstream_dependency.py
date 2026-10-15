from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable, Mapping

from trading_platform.v21.event_store import EventStore, sha256_json


class DownstreamDependencyError(RuntimeError):
    """A downstream artifact is not safely bound to its required upstreams."""


class DownstreamDependencyConflict(DownstreamDependencyError):
    pass


class DownstreamDependencyBlocked(DownstreamDependencyError):
    pass


@dataclass(frozen=True)
class DependencyReference:
    event_id: str
    expected_event_type: str
    expected_aggregate_id: str | None = None
    expected_fingerprint: str | None = None
    allowed_states: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownstreamDependencyAuthorization:
    authorization_id: str
    artifact_id: str
    artifact_type: str
    dependency_event_ids: tuple[str, ...]
    dependency_event_hashes: tuple[str, ...]
    dependency_contracts: tuple[dict[str, Any], ...]
    dependency_checkpoint_sequence: int
    authorized_at_ms: int
    fingerprint: str


class DownstreamDependencyAuthorityLedger:
    """Durable precondition authority for downstream artifact creation.

    An artifact can only be committed after this authority proves every required
    upstream event exists, has the expected type/aggregate/fingerprint, and is in
    an allowed state. Later use rechecks the same bindings, so a downstream artifact
    cannot be treated as valid merely because its historical upstream once existed.
    """

    RECORDED = "DOWNSTREAM_DEPENDENCY_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _event_fingerprint(event: Any) -> str:
        return str(event.event_hash)

    @staticmethod
    def _payload_state(event: Any) -> str | None:
        value = event.payload.get("state")
        return None if value is None else str(value)

    def _validate_reference(self, ref: DependencyReference, *, now_ms: int) -> Any:
        if not ref.event_id or not ref.expected_event_type:
            raise ValueError("DOWNSTREAM_DEPENDENCY_REFERENCE_REQUIRED")
        event = self.store.get(ref.event_id)
        if event is None:
            raise DownstreamDependencyBlocked(f"UPSTREAM_NOT_FOUND:{ref.event_id}")
        if event.event_type != ref.expected_event_type:
            raise DownstreamDependencyBlocked(
                f"UPSTREAM_EVENT_TYPE_MISMATCH:{ref.event_id}:{event.event_type}"
            )
        if ref.expected_aggregate_id is not None and event.aggregate_id != ref.expected_aggregate_id:
            raise DownstreamDependencyBlocked(f"UPSTREAM_AGGREGATE_MISMATCH:{ref.event_id}")
        if ref.expected_fingerprint is not None:
            actual = sha256_json(dict(event.payload))
            if actual != ref.expected_fingerprint:
                raise DownstreamDependencyBlocked(f"UPSTREAM_FINGERPRINT_MISMATCH:{ref.event_id}")
        if ref.allowed_states:
            state = self._payload_state(event)
            if state not in set(ref.allowed_states):
                raise DownstreamDependencyBlocked(
                    f"UPSTREAM_STATE_DENIED:{ref.event_id}:{state}"
                )
        valid_from = event.payload.get("valid_from_ms")
        expires_at = event.payload.get("expires_at_ms")
        if valid_from is not None and expires_at is not None:
            try:
                vf = int(valid_from)
                ex = int(expires_at)
            except Exception as exc:
                raise DownstreamDependencyBlocked(f"UPSTREAM_WINDOW_INVALID:{ref.event_id}") from exc
            if ex <= vf or not (vf <= int(now_ms) < ex):
                raise DownstreamDependencyBlocked(f"UPSTREAM_EXPIRED:{ref.event_id}")
        return event

    @staticmethod
    def _semantic_payload(record: DownstreamDependencyAuthorization) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "dependency_event_ids": list(record.dependency_event_ids),
            "dependency_event_hashes": list(record.dependency_event_hashes),
            "dependency_contracts": list(record.dependency_contracts),
            "dependency_checkpoint_sequence": record.dependency_checkpoint_sequence,
        }

    @classmethod
    def _fingerprint(cls, record: DownstreamDependencyAuthorization) -> str:
        return sha256_json(cls._semantic_payload(record))

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> DownstreamDependencyAuthorization:
        try:
            record = DownstreamDependencyAuthorization(
                authorization_id=str(payload["authorization_id"]),
                artifact_id=str(payload["artifact_id"]),
                artifact_type=str(payload["artifact_type"]),
                dependency_event_ids=tuple(str(v) for v in payload["dependency_event_ids"]),
                dependency_event_hashes=tuple(str(v) for v in payload["dependency_event_hashes"]),
                dependency_contracts=tuple(dict(v) for v in payload.get("dependency_contracts", [])),
                dependency_checkpoint_sequence=int(payload["dependency_checkpoint_sequence"]),
                authorized_at_ms=int(payload["authorized_at_ms"]),
                fingerprint=str(payload["fingerprint"]),
            )
        except Exception as exc:
            raise DownstreamDependencyError("INVALID_DOWNSTREAM_DEPENDENCY_PAYLOAD") from exc
        if not record.authorization_id or not record.artifact_id or not record.artifact_type:
            raise DownstreamDependencyError("DOWNSTREAM_DEPENDENCY_IDENTIFIERS_REQUIRED")
        if len(record.dependency_event_ids) != len(record.dependency_event_hashes) or len(record.dependency_event_ids) != len(record.dependency_contracts):
            raise DownstreamDependencyError("DOWNSTREAM_DEPENDENCY_CARDINALITY_INVALID")
        if record.dependency_checkpoint_sequence < 0 or record.authorized_at_ms < 0:
            raise DownstreamDependencyError("DOWNSTREAM_DEPENDENCY_TIMESTAMP_INVALID")
        if cls._fingerprint(record) != record.fingerprint:
            raise DownstreamDependencyError("DOWNSTREAM_DEPENDENCY_FINGERPRINT_MISMATCH")
        return record

    def authorize(
        self,
        *,
        authorization_id: str,
        artifact_id: str,
        artifact_type: str,
        dependencies: Iterable[DependencyReference],
        now_ms: int,
    ) -> DownstreamDependencyAuthorization:
        if not authorization_id or not artifact_id or not artifact_type:
            raise ValueError("DOWNSTREAM_DEPENDENCY_IDENTIFIERS_REQUIRED")
        if now_ms < 0:
            raise ValueError("DOWNSTREAM_DEPENDENCY_TIMESTAMP_INVALID")
        if not self.store.verify_chain():
            raise DownstreamDependencyError("EVENT_CHAIN_INVALID")
        refs = tuple(dependencies)
        if not refs:
            raise DownstreamDependencyBlocked("UPSTREAM_DEPENDENCIES_REQUIRED")
        if len({ref.event_id for ref in refs}) != len(refs):
            raise DownstreamDependencyConflict("DUPLICATE_UPSTREAM_REFERENCE")
        events = tuple(self._validate_reference(ref, now_ms=now_ms) for ref in refs)
        event_ids = tuple(ref.event_id for ref in refs)
        event_hashes = tuple(self._event_fingerprint(event) for event in events)
        contracts = tuple({"event_id": ref.event_id, "expected_event_type": ref.expected_event_type, "expected_aggregate_id": ref.expected_aggregate_id, "expected_fingerprint": ref.expected_fingerprint, "allowed_states": list(ref.allowed_states)} for ref in refs)
        checkpoint = self.store.latest_sequence()
        record = DownstreamDependencyAuthorization(
            authorization_id=authorization_id,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            dependency_event_ids=event_ids,
            dependency_event_hashes=event_hashes,
            dependency_contracts=contracts,
            dependency_checkpoint_sequence=checkpoint,
            authorized_at_ms=now_ms,
            fingerprint="",
        )
        record = DownstreamDependencyAuthorization(
            **{**record.__dict__, "fingerprint": self._fingerprint(record)}
        )
        payload = {**self._semantic_payload(record), "authorized_at_ms": record.authorized_at_ms, "fingerprint": record.fingerprint}
        event_id = f"downstream-dependency:authorize:{authorization_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            restored = self._from_payload(existing.payload)
            if self._semantic_payload(restored) != self._semantic_payload(record):
                raise DownstreamDependencyConflict("DOWNSTREAM_DEPENDENCY_ID_CONFLICT")
            return self.assert_valid(
                authorization_id,
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                now_ms=now_ms,
            )
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=now_ms,
            event_type=self.RECORDED,
            aggregate_id=artifact_id,
            payload=payload,
        )
        return self._from_payload(result.event.payload)

    def get(self, authorization_id: str) -> DownstreamDependencyAuthorization | None:
        if not self.store.verify_chain():
            raise DownstreamDependencyError("EVENT_CHAIN_INVALID")
        event = self.store.get(f"downstream-dependency:authorize:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise DownstreamDependencyError("DOWNSTREAM_DEPENDENCY_EVENT_TYPE_MISMATCH")
        return self._from_payload(event.payload)

    def assert_valid(
        self,
        authorization_id: str,
        *,
        artifact_id: str,
        artifact_type: str,
        now_ms: int,
    ) -> DownstreamDependencyAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise DownstreamDependencyBlocked("DOWNSTREAM_DEPENDENCY_AUTHORIZATION_NOT_FOUND")
        if record.artifact_id != artifact_id:
            raise DownstreamDependencyConflict("DOWNSTREAM_DEPENDENCY_ARTIFACT_MISMATCH")
        if record.artifact_type != artifact_type:
            raise DownstreamDependencyConflict("DOWNSTREAM_DEPENDENCY_ARTIFACT_TYPE_MISMATCH")
        current_hashes: list[str] = []
        for contract, expected_hash in zip(record.dependency_contracts, record.dependency_event_hashes):
            ref = DependencyReference(
                event_id=str(contract["event_id"]),
                expected_event_type=str(contract["expected_event_type"]),
                expected_aggregate_id=(None if contract.get("expected_aggregate_id") is None else str(contract["expected_aggregate_id"])),
                expected_fingerprint=(None if contract.get("expected_fingerprint") is None else str(contract["expected_fingerprint"])),
                allowed_states=tuple(str(v) for v in contract.get("allowed_states", [])),
            )
            event = self._validate_reference(ref, now_ms=now_ms)
            current_hashes.append(self._event_fingerprint(event))
            if current_hashes[-1] != expected_hash:
                raise DownstreamDependencyBlocked(f"UPSTREAM_CHANGED:{ref.event_id}")
        if tuple(current_hashes) != record.dependency_event_hashes:
            raise DownstreamDependencyBlocked("UPSTREAM_DEPENDENCY_CHANGED")
        if self.store.latest_sequence() < record.dependency_checkpoint_sequence:
            raise DownstreamDependencyError("DEPENDENCY_CHECKPOINT_INVALID")
        return record



def require_upstream_events(
    store: EventStore,
    *,
    artifact_id: str,
    artifact_type: str,
    dependencies: Iterable[DependencyReference],
    now_ms: int,
    authorization_id: str | None = None,
) -> DownstreamDependencyAuthorization:
    ledger = DownstreamDependencyAuthorityLedger(store)
    auth_id = authorization_id or f"auto:{artifact_type}:{artifact_id}"
    return ledger.authorize(
        authorization_id=auth_id,
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        dependencies=dependencies,
        now_ms=now_ms,
    )

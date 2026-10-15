from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore, sha256_json


class CausalTTLConflict(RuntimeError):
    """The causal TTL chain cannot safely authorize the downstream artifact."""


class CausalTTLReplayError(RuntimeError):
    """The durable causal TTL history cannot be reconstructed safely."""


class CausalArtifactType(str, Enum):
    PREDICTION = "PREDICTION"
    SIGNAL = "SIGNAL"
    OPPORTUNITY = "OPPORTUNITY"
    PORTFOLIO_DECISION = "PORTFOLIO_DECISION"
    RISK_DECISION = "RISK_DECISION"
    ORDER_INTENT = "ORDER_INTENT"


class CausalArtifactState(str, Enum):
    VALID = "VALID"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class CausalArtifactRecord:
    artifact_id: str
    artifact_type: CausalArtifactType
    version: str
    state: CausalArtifactState
    valid_from_ms: int
    expires_at_ms: int
    dependencies: tuple[str, ...]
    fingerprint: str

    def payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "version": self.version,
            "state": self.state.value,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
            "dependencies": list(self.dependencies),
            "fingerprint": self.fingerprint,
        }


class CausalTTLAuthorityLedger:
    """Durable authority for Prediction→Signal→Opportunity→Portfolio→Risk→Intent TTLs.

    This ledger is the machine-enforced cross-domain TTL boundary. A downstream artifact
    may only be recorded when every required upstream artifact exists, is temporally valid,
    and has an expiry no earlier than the downstream artifact. Runtime authorization then
    replays the complete graph and validates the chain at the dispatch timestamp.
    """

    RECORDED = "CAUSAL_TTL_ARTIFACT_RECORDED"

    _REQUIRED_DEPENDENCY_TYPE: Mapping[CausalArtifactType, CausalArtifactType | None] = {
        CausalArtifactType.PREDICTION: None,
        CausalArtifactType.SIGNAL: CausalArtifactType.PREDICTION,
        CausalArtifactType.OPPORTUNITY: CausalArtifactType.SIGNAL,
        CausalArtifactType.PORTFOLIO_DECISION: CausalArtifactType.OPPORTUNITY,
        CausalArtifactType.RISK_DECISION: CausalArtifactType.PORTFOLIO_DECISION,
        CausalArtifactType.ORDER_INTENT: CausalArtifactType.RISK_DECISION,
    }

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _normalize_dependencies(dependencies: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        out = tuple(str(x) for x in dependencies)
        if any(not x for x in out):
            raise ValueError("CAUSAL_TTL_DEPENDENCY_ID_REQUIRED")
        if len(set(out)) != len(out):
            raise ValueError("CAUSAL_TTL_DUPLICATE_DEPENDENCY")
        return out

    @classmethod
    def _fingerprint_payload(
        cls,
        *,
        artifact_id: str,
        artifact_type: CausalArtifactType,
        version: str,
        state: CausalArtifactState,
        valid_from_ms: int,
        expires_at_ms: int,
        dependencies: tuple[str, ...],
    ) -> str:
        return sha256_json({
            "artifact_id": artifact_id,
            "artifact_type": artifact_type.value,
            "version": version,
            "state": state.value,
            "valid_from_ms": valid_from_ms,
            "expires_at_ms": expires_at_ms,
            "dependencies": list(dependencies),
        })

    def record_artifact(
        self,
        *,
        artifact_id: str,
        artifact_type: CausalArtifactType,
        version: str,
        state: CausalArtifactState,
        valid_from_ms: int,
        expires_at_ms: int,
        dependencies: tuple[str, ...] | list[str] = (),
        recorded_at_ms: int | None = None,
    ) -> CausalArtifactRecord:
        if not artifact_id or not version:
            raise ValueError("CAUSAL_TTL_ARTIFACT_FIELDS_REQUIRED")
        if valid_from_ms < 0 or expires_at_ms <= valid_from_ms:
            raise ValueError("CAUSAL_TTL_INVALID_WINDOW")
        deps = self._normalize_dependencies(dependencies)
        recorded_at = valid_from_ms if recorded_at_ms is None else int(recorded_at_ms)
        if recorded_at < valid_from_ms or recorded_at >= expires_at_ms:
            raise ValueError("CAUSAL_TTL_RECORD_OUTSIDE_WINDOW")

        required_type = self._REQUIRED_DEPENDENCY_TYPE[artifact_type]
        if required_type is None:
            if deps:
                raise ValueError("CAUSAL_TTL_ROOT_DEPENDENCY_NOT_ALLOWED")
        else:
            matching = []
            for dependency_id in deps:
                dependency = self.get(dependency_id)
                if dependency is None:
                    raise CausalTTLConflict(f"CAUSAL_TTL_UPSTREAM_NOT_FOUND:{dependency_id}")
                if dependency.state not in {CausalArtifactState.VALID, CausalArtifactState.APPROVED, CausalArtifactState.ACTIVE}:
                    raise CausalTTLConflict(f"CAUSAL_TTL_UPSTREAM_INVALID:{dependency_id}")
                if not (dependency.valid_from_ms <= recorded_at < dependency.expires_at_ms):
                    raise CausalTTLConflict(f"CAUSAL_TTL_UPSTREAM_EXPIRED:{dependency_id}")
                if expires_at_ms > dependency.expires_at_ms:
                    raise CausalTTLConflict(f"CAUSAL_TTL_DOWNSTREAM_OUTLIVES_UPSTREAM:{artifact_id}:{dependency_id}")
                if dependency.artifact_type is required_type:
                    matching.append(dependency)
            if not matching:
                raise CausalTTLConflict(f"CAUSAL_TTL_REQUIRED_DEPENDENCY_TYPE_MISSING:{artifact_type.value}:{required_type.value}")

        fp = self._fingerprint_payload(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            state=state,
            valid_from_ms=valid_from_ms,
            expires_at_ms=expires_at_ms,
            dependencies=deps,
        )
        payload = {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type.value,
            "version": version,
            "state": state.value,
            "valid_from_ms": valid_from_ms,
            "expires_at_ms": expires_at_ms,
            "dependencies": list(deps),
            "fingerprint": fp,
        }
        event_id = f"causal-ttl:record:{artifact_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED or dict(existing.payload) != payload:
                raise CausalTTLConflict("CAUSAL_TTL_ARTIFACT_ID_PAYLOAD_CONFLICT")
            return self._from_payload(existing.payload)
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=recorded_at,
            event_type=self.RECORDED,
            aggregate_id=artifact_id,
            payload=payload,
        )
        if result.duplicate and dict(result.event.payload) != payload:
            raise CausalTTLConflict("CAUSAL_TTL_ARTIFACT_ID_PAYLOAD_CONFLICT")
        return self._from_payload(result.event.payload)

    def restore(self) -> dict[str, CausalArtifactRecord]:
        if not self.store.verify_chain():
            raise CausalTTLReplayError("CAUSAL_TTL_EVENT_CHAIN_INVALID")
        out: dict[str, CausalArtifactRecord] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                raise CausalTTLReplayError(f"UNKNOWN_CAUSAL_TTL_EVENT_TYPE:{event.event_type}")
            record = self._from_payload(event.payload)
            if event.aggregate_id != record.artifact_id:
                raise CausalTTLReplayError("CAUSAL_TTL_AGGREGATE_MISMATCH")
            if record.artifact_id in out:
                raise CausalTTLReplayError("DUPLICATE_CAUSAL_TTL_ARTIFACT_ID")
            out[record.artifact_id] = record
        return out

    def get(self, artifact_id: str) -> CausalArtifactRecord | None:
        event = self.store.get(f"causal-ttl:record:{artifact_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise CausalTTLReplayError("CAUSAL_TTL_EVENT_TYPE_MISMATCH")
        return self._from_payload(event.payload)

    def assert_intent_chain_valid(
        self,
        *,
        intent_id: str,
        now_ms: int,
        expected_valid_from_ms: int | None = None,
        expected_expires_at_ms: int | None = None,
    ) -> CausalArtifactRecord:
        if now_ms < 0:
            raise CausalTTLConflict("CAUSAL_TTL_INVALID_CLOCK")
        if not self.store.verify_chain():
            raise CausalTTLConflict("CAUSAL_TTL_EVENT_CHAIN_INVALID")
        root = self.get(intent_id)
        if root is None:
            raise CausalTTLConflict("CAUSAL_TTL_INTENT_NOT_FOUND")
        if root.artifact_type is not CausalArtifactType.ORDER_INTENT:
            raise CausalTTLConflict("CAUSAL_TTL_ROOT_NOT_ORDER_INTENT")
        if expected_valid_from_ms is not None and root.valid_from_ms != expected_valid_from_ms:
            raise CausalTTLConflict("CAUSAL_TTL_INTENT_VALID_FROM_MISMATCH")
        if expected_expires_at_ms is not None and root.expires_at_ms != expected_expires_at_ms:
            raise CausalTTLConflict("CAUSAL_TTL_INTENT_EXPIRES_AT_MISMATCH")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(artifact_id: str, expected_type: CausalArtifactType | None = None) -> CausalArtifactRecord:
            if artifact_id in visiting:
                raise CausalTTLConflict("CAUSAL_TTL_CYCLE_DETECTED")
            record = self.get(artifact_id)
            if record is None:
                raise CausalTTLConflict(f"CAUSAL_TTL_UPSTREAM_NOT_FOUND:{artifact_id}")
            if expected_type is not None and record.artifact_type is not expected_type:
                raise CausalTTLConflict(f"CAUSAL_TTL_TYPE_MISMATCH:{artifact_id}")
            if record.state not in {CausalArtifactState.VALID, CausalArtifactState.APPROVED, CausalArtifactState.ACTIVE}:
                raise CausalTTLConflict(f"CAUSAL_TTL_STATE_DENIED:{artifact_id}:{record.state.value}")
            if not (record.valid_from_ms <= now_ms < record.expires_at_ms):
                raise CausalTTLConflict(f"CAUSAL_TTL_EXPIRED:{artifact_id}")
            if artifact_id in visited:
                return record
            visiting.add(artifact_id)
            required = self._REQUIRED_DEPENDENCY_TYPE[record.artifact_type]
            if required is None:
                if record.dependencies:
                    raise CausalTTLConflict(f"CAUSAL_TTL_UNEXPECTED_DEPENDENCIES:{artifact_id}")
            else:
                deps = [self.get(dep_id) for dep_id in record.dependencies]
                if not any(d is not None and d.artifact_type is required for d in deps):
                    raise CausalTTLConflict(f"CAUSAL_TTL_REQUIRED_DEPENDENCY_MISSING:{artifact_id}:{required.value}")
                for dependency_id in record.dependencies:
                    dependency = visit(dependency_id)
                    if record.expires_at_ms > dependency.expires_at_ms:
                        raise CausalTTLConflict(f"CAUSAL_TTL_DOWNSTREAM_OUTLIVES_UPSTREAM:{artifact_id}:{dependency_id}")
            visiting.remove(artifact_id)
            visited.add(artifact_id)
            return record

        return visit(intent_id, CausalArtifactType.ORDER_INTENT)

    @staticmethod
    def _from_payload(payload: Mapping[str, Any]) -> CausalArtifactRecord:
        try:
            artifact_id = str(payload["artifact_id"])
            artifact_type = CausalArtifactType(str(payload["artifact_type"]))
            version = str(payload["version"])
            state = CausalArtifactState(str(payload["state"]))
            valid_from_ms = int(payload["valid_from_ms"])
            expires_at_ms = int(payload["expires_at_ms"])
            dependencies = tuple(str(x) for x in payload.get("dependencies", []))
            fingerprint = str(payload["fingerprint"])
        except Exception as exc:
            raise CausalTTLReplayError("INVALID_CAUSAL_TTL_PAYLOAD") from exc
        expected = CausalTTLAuthorityLedger._fingerprint_payload(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            state=state,
            valid_from_ms=valid_from_ms,
            expires_at_ms=expires_at_ms,
            dependencies=dependencies,
        )
        if fingerprint != expected:
            raise CausalTTLReplayError("CAUSAL_TTL_FINGERPRINT_MISMATCH")
        if expires_at_ms <= valid_from_ms:
            raise CausalTTLReplayError("CAUSAL_TTL_INVALID_WINDOW")
        return CausalArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            version=version,
            state=state,
            valid_from_ms=valid_from_ms,
            expires_at_ms=expires_at_ms,
            dependencies=dependencies,
            fingerprint=fingerprint,
        )

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.research.methods import MethodCheck, MethodSpec, MethodStatus, check_assumptions
from trading_platform.v21.event_store import EventStore


class MethodApplicabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MethodRegistryRecord:
    method_id: str
    version: str
    assumptions: tuple[str, ...]
    applicability: str
    limitations: tuple[str, ...]
    implementation_reference: str
    required_inputs: tuple[str, ...]
    output_semantics: str

    @classmethod
    def from_spec(cls, spec: MethodSpec) -> "MethodRegistryRecord":
        record = cls(
            method_id=spec.method_id,
            version=spec.version,
            assumptions=tuple(spec.assumptions),
            applicability=spec.applicability,
            limitations=tuple(spec.limitations),
            implementation_reference=spec.implementation_reference,
            required_inputs=tuple(spec.required_inputs),
            output_semantics=spec.output_semantics,
        )
        record.validate()
        return record

    def validate(self) -> None:
        if not self.method_id or not self.version:
            raise ValueError("METHOD_IDENTITY_REQUIRED")
        if not self.assumptions:
            raise ValueError("METHOD_ASSUMPTIONS_REQUIRED")
        if not self.applicability:
            raise ValueError("METHOD_APPLICABILITY_REQUIRED")
        if not self.implementation_reference:
            raise ValueError("METHOD_IMPLEMENTATION_REFERENCE_REQUIRED")
        if not self.output_semantics:
            raise ValueError("METHOD_OUTPUT_SEMANTICS_REQUIRED")

    def fingerprint(self) -> str:
        self.validate()
        payload = asdict(self)
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_spec(self) -> MethodSpec:
        return MethodSpec(
            method_id=self.method_id,
            version=self.version,
            assumptions=self.assumptions,
            applicability=self.applicability,
            limitations=self.limitations,
            implementation_reference=self.implementation_reference,
            required_inputs=self.required_inputs,
            output_semantics=self.output_semantics,
        )


class StatisticalMethodRegistry:
    EVENT_TYPE = "STATISTICAL_METHOD_REGISTERED"

    def __init__(self, store: EventStore):
        self.store = store

    @staticmethod
    def _event_id(method_id: str, version: str) -> str:
        return f"method-registry:{method_id}:{version}"

    def register(self, spec: MethodSpec, *, recorded_at_ms: int) -> MethodRegistryRecord:
        record = MethodRegistryRecord.from_spec(spec)
        event_id = self._event_id(record.method_id, record.version)
        existing = self.store.get(event_id)
        if existing is not None:
            payload = dict(existing.payload)
            if payload.get("record_fingerprint") != record.fingerprint():
                raise MethodApplicabilityError("METHOD_REGISTRY_FINGERPRINT_CONFLICT")
            return record
        self.store.append(
            event_id=event_id,
            occurred_at_ms=int(recorded_at_ms),
            event_type=self.EVENT_TYPE,
            aggregate_id=f"{record.method_id}:{record.version}",
            payload={
                "method_id": record.method_id,
                "version": record.version,
                "record_fingerprint": record.fingerprint(),
                "assumptions": list(record.assumptions),
                "applicability": record.applicability,
                "limitations": list(record.limitations),
                "implementation_reference": record.implementation_reference,
                "required_inputs": list(record.required_inputs),
                "output_semantics": record.output_semantics,
            },
        )
        return record

    def get(self, method_id: str, version: str) -> MethodRegistryRecord:
        event = self.store.get(self._event_id(method_id, version))
        if event is None:
            raise MethodApplicabilityError("METHOD_NOT_REGISTERED")
        payload = dict(event.payload)
        record = MethodRegistryRecord(
            method_id=str(payload["method_id"]),
            version=str(payload["version"]),
            assumptions=tuple(str(v) for v in payload["assumptions"]),
            applicability=str(payload["applicability"]),
            limitations=tuple(str(v) for v in payload["limitations"]),
            implementation_reference=str(payload["implementation_reference"]),
            required_inputs=tuple(str(v) for v in payload["required_inputs"]),
            output_semantics=str(payload["output_semantics"]),
        )
        if record.fingerprint() != payload.get("record_fingerprint"):
            raise MethodApplicabilityError("METHOD_REGISTRY_TAMPERED")
        return record


@dataclass(frozen=True)
class MethodApplicabilityDecision:
    decision_id: str
    method_id: str
    version: str
    status: MethodStatus
    failed_assumptions: tuple[str, ...]
    assumption_results_fingerprint: str
    registry_fingerprint: str
    checked_at_ms: int

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MethodApplicabilityLedger:
    EVENT_TYPE = "METHOD_APPLICABILITY_CHECKED"

    def __init__(self, store: EventStore, registry: StatisticalMethodRegistry | None = None):
        self.store = store
        self.registry = registry or StatisticalMethodRegistry(store)

    @staticmethod
    def _results_fingerprint(assumption_results: Mapping[str, bool]) -> str:
        payload = {str(k): bool(v) for k, v in sorted(assumption_results.items())}
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def assess(
        self,
        *,
        method_id: str,
        version: str,
        assumption_results: Mapping[str, bool],
        checked_at_ms: int,
        decision_id: str | None = None,
    ) -> MethodApplicabilityDecision:
        record = self.registry.get(method_id, version)
        spec = record.to_spec()
        check: MethodCheck = check_assumptions(spec, dict(assumption_results))
        decision_id = decision_id or f"method-applicability:{method_id}:{version}:{checked_at_ms}"
        decision = MethodApplicabilityDecision(
            decision_id=decision_id,
            method_id=method_id,
            version=version,
            status=check.status,
            failed_assumptions=check.failed_assumptions,
            assumption_results_fingerprint=self._results_fingerprint(assumption_results),
            registry_fingerprint=record.fingerprint(),
            checked_at_ms=int(checked_at_ms),
        )
        existing = self.store.get(decision_id)
        payload = {
            "decision_id": decision.decision_id,
            "method_id": decision.method_id,
            "version": decision.version,
            "status": decision.status.value,
            "failed_assumptions": list(decision.failed_assumptions),
            "assumption_results_fingerprint": decision.assumption_results_fingerprint,
            "registry_fingerprint": decision.registry_fingerprint,
            "checked_at_ms": decision.checked_at_ms,
            "decision_fingerprint": decision.fingerprint(),
        }
        if existing is None:
            self.store.append(
                event_id=decision_id,
                occurred_at_ms=decision.checked_at_ms,
                event_type=self.EVENT_TYPE,
                aggregate_id=f"{method_id}:{version}",
                payload=payload,
            )
        elif dict(existing.payload) != payload:
            raise MethodApplicabilityError("METHOD_APPLICABILITY_DECISION_CONFLICT")
        return decision

    def assert_valid(
        self,
        decision_id: str,
        *,
        now_ms: int,
        method_id: str,
        version: str,
        assumption_results: Mapping[str, bool],
    ) -> MethodApplicabilityDecision:
        event = self.store.get(decision_id)
        if event is None:
            raise MethodApplicabilityError("METHOD_APPLICABILITY_DECISION_NOT_FOUND")
        payload = dict(event.payload)
        record = self.registry.get(method_id, version)
        expected_results = self._results_fingerprint(assumption_results)
        if payload.get("method_id") != method_id or payload.get("version") != version:
            raise MethodApplicabilityError("METHOD_APPLICABILITY_BINDING_MISMATCH")
        if payload.get("registry_fingerprint") != record.fingerprint():
            raise MethodApplicabilityError("METHOD_APPLICABILITY_METHOD_CHANGED")
        if payload.get("assumption_results_fingerprint") != expected_results:
            raise MethodApplicabilityError("METHOD_APPLICABILITY_ASSUMPTIONS_CHANGED")
        if int(now_ms) < int(payload.get("checked_at_ms", 0)):
            raise MethodApplicabilityError("METHOD_APPLICABILITY_TIME_REVERSED")
        try:
            status = MethodStatus(str(payload["status"]))
        except ValueError as exc:
            raise MethodApplicabilityError("METHOD_APPLICABILITY_STATUS_INVALID") from exc
        decision = MethodApplicabilityDecision(
            decision_id=str(payload["decision_id"]), method_id=method_id, version=version,
            status=status, failed_assumptions=tuple(str(v) for v in payload.get("failed_assumptions", [])),
            assumption_results_fingerprint=str(payload["assumption_results_fingerprint"]),
            registry_fingerprint=str(payload["registry_fingerprint"]), checked_at_ms=int(payload["checked_at_ms"]),
        )
        if decision.fingerprint() != payload.get("decision_fingerprint"):
            raise MethodApplicabilityError("METHOD_APPLICABILITY_TAMPERED")
        if decision.status is not MethodStatus.APPLICABLE:
            raise MethodApplicabilityError(f"METHOD_NOT_APPLICABLE:{','.join(decision.failed_assumptions)}")
        return decision


class GuardedMethodExecutor:
    """Execute a statistical method only after durable applicability is established."""

    def __init__(self, ledger: MethodApplicabilityLedger):
        self.ledger = ledger

    def execute(
        self,
        *,
        method_id: str,
        version: str,
        assumption_results: Mapping[str, bool],
        checked_at_ms: int,
        evaluator: Any,
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        decision = self.ledger.assess(
            method_id=method_id, version=version, assumption_results=assumption_results,
            checked_at_ms=checked_at_ms,
        )
        if decision.status is not MethodStatus.APPLICABLE:
            raise MethodApplicabilityError(f"METHOD_NOT_APPLICABLE:{','.join(decision.failed_assumptions)}")
        self.ledger.assert_valid(
            decision.decision_id, now_ms=checked_at_ms, method_id=method_id,
            version=version, assumption_results=assumption_results,
        )
        return evaluator(*args, **dict(kwargs or {}))

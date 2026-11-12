from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Any
from .compatibility import OrthogonalState, validate_state
from .enums import OperationalMode


# This engine is intentionally narrower than the platform lifecycle contract.
# Only transitions in this registry can commit; the named lifecycle and risk
# machines are documented separately and currently default to rejection.
def _is_registered_transition(spec: "TransitionSpec") -> bool:
    if spec.action != "START_BACKTEST":
        return False
    source = spec.source
    target = spec.target
    return (
        source.mode == OperationalMode.RESEARCH
        and target.mode == OperationalMode.BACKTEST
        and source.lifecycle == target.lifecycle
        and source.health == target.health
        and source.approval == target.approval
        and source.deployment == target.deployment
        and source.role == target.role
    )


@dataclass(frozen=True)
class TransitionSpec:
    transition_id: str
    source: OrthogonalState
    target: OrthogonalState
    action: str
    guard: Callable[[OrthogonalState, Any], None] | None = None
    idempotency_key: str = ""
    audit_event_type: str = "STATE_TRANSITION"

class TransitionEngine:
    def __init__(self) -> None:
        self._committed: dict[str, tuple[TransitionSpec, OrthogonalState]] = {}
        self._audit: list[dict[str, Any]] = []

    def apply(self, spec: TransitionSpec, context: Any = None) -> OrthogonalState:
        if not isinstance(spec.idempotency_key, str) or not spec.idempotency_key.strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        committed = self._committed.get(spec.idempotency_key)
        if committed is not None:
            committed_spec, committed_state = committed
            if committed_spec != spec:
                raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
            return committed_state
        ok, errors = validate_state(spec.source)
        if not ok:
            raise ValueError(f"INVALID_SOURCE_STATE:{errors}")
        ok, errors = validate_state(spec.target)
        if not ok:
            raise ValueError(f"INVALID_TARGET_STATE:{errors}")
        if not _is_registered_transition(spec):
            raise ValueError("UNDECLARED_TRANSITION")
        if spec.guard is not None:
            spec.guard(spec.source, context)
        event = {
            "transition_id": spec.transition_id,
            "action": spec.action,
            "event_type": spec.audit_event_type,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._committed[spec.idempotency_key] = (spec, spec.target)
        self._audit.append(event)
        return spec.target

    @property
    def audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._audit)

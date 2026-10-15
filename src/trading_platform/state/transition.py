from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Any
from .compatibility import OrthogonalState, validate_state

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
        self._committed: dict[str, OrthogonalState] = {}
        self._audit: list[dict[str, Any]] = []

    def apply(self, spec: TransitionSpec, context: Any = None) -> OrthogonalState:
        if not spec.idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if spec.idempotency_key in self._committed:
            return self._committed[spec.idempotency_key]
        ok, errors = validate_state(spec.source)
        if not ok:
            raise ValueError(f"INVALID_SOURCE_STATE:{errors}")
        ok, errors = validate_state(spec.target)
        if not ok:
            raise ValueError(f"INVALID_TARGET_STATE:{errors}")
        if spec.guard is not None:
            spec.guard(spec.source, context)
        event = {"transition_id": spec.transition_id, "action": spec.action, "committed_at": datetime.now(timezone.utc).isoformat()}
        self._committed[spec.idempotency_key] = spec.target
        self._audit.append(event)
        return spec.target

    @property
    def audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._audit)

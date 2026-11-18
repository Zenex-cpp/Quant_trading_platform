import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any
from .compatibility import OrthogonalState, validate_state
from .enums import Approval, Deployment, Health, Lifecycle, OperationalMode, Role


# This engine is intentionally narrower than the platform lifecycle contract.
# Only transitions in this registry can commit; the named lifecycle and risk
# machines are documented separately and currently default to rejection.
def _is_registered_transition(spec: "TransitionSpec") -> bool:
    if spec.action != "START_BACKTEST" or spec.audit_event_type != "STATE_TRANSITION":
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


_STATE_FIELDS = ("lifecycle", "mode", "health", "approval", "deployment", "role")


def _state_document(state: OrthogonalState) -> dict[str, str]:
    return {name: getattr(state, name).value for name in _STATE_FIELDS}


def _state_json(state: OrthogonalState) -> str:
    return json.dumps(_state_document(state), sort_keys=True, separators=(",", ":"))


def _state_from_json(value: str) -> OrthogonalState:
    try:
        document = json.loads(value)
        if not isinstance(document, dict) or set(document) != set(_STATE_FIELDS):
            raise ValueError("invalid state shape")
        return OrthogonalState(
            lifecycle=Lifecycle(document["lifecycle"]),
            mode=OperationalMode(document["mode"]),
            health=Health(document["health"]),
            approval=Approval(document["approval"]),
            deployment=Deployment(document["deployment"]),
            role=Role(document["role"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("TRANSITION_STORE_CORRUPTED") from exc


def _canonical_spec(spec: TransitionSpec) -> str:
    document = {
        "action": spec.action,
        "audit_event_type": spec.audit_event_type,
        "idempotency_key": spec.idempotency_key,
        "source": _state_document(spec.source),
        "target": _state_document(spec.target),
        "transition_id": spec.transition_id,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_persistent_spec(spec: TransitionSpec) -> None:
    if not isinstance(spec, TransitionSpec):
        raise ValueError("INVALID_TRANSITION_SPEC")
    if not isinstance(spec.transition_id, str) or not spec.transition_id.strip():
        raise ValueError("TRANSITION_ID_REQUIRED")
    if not isinstance(spec.action, str) or not spec.action.strip():
        raise ValueError("TRANSITION_ACTION_REQUIRED")
    if not isinstance(spec.audit_event_type, str) or not spec.audit_event_type.strip():
        raise ValueError("AUDIT_EVENT_TYPE_REQUIRED")
    if not isinstance(spec.source, OrthogonalState):
        raise ValueError("INVALID_SOURCE_STATE")
    if not isinstance(spec.target, OrthogonalState):
        raise ValueError("INVALID_TARGET_STATE")
    enum_types = (Lifecycle, OperationalMode, Health, Approval, Deployment, Role)
    for state, label in ((spec.source, "SOURCE"), (spec.target, "TARGET")):
        if any(not isinstance(getattr(state, name), enum_type) for name, enum_type in zip(_STATE_FIELDS, enum_types)):
            raise ValueError(f"INVALID_{label}_STATE")


class PersistentTransitionEngine:
    """SQLite-backed atomic state and audit commits for registered transitions.

    This implementation accepts only transitions without a caller-supplied
    callback. State, idempotency record, and audit event are committed in one
    local SQLite transaction; it does not execute external side effects.
    """

    SCHEMA_VERSION = 1

    def __init__(self, database_path: str | Path, initial_state: OrthogonalState) -> None:
        if not isinstance(database_path, (str, Path)):
            raise ValueError("DURABLE_DATABASE_PATH_REQUIRED")
        path = str(database_path)
        if not path or path == ":memory:" or "mode=memory" in path:
            raise ValueError("DURABLE_DATABASE_PATH_REQUIRED")
        if not isinstance(initial_state, OrthogonalState):
            raise ValueError("INVALID_INITIAL_STATE")
        enum_types = (Lifecycle, OperationalMode, Health, Approval, Deployment, Role)
        if any(
            not isinstance(getattr(initial_state, name), enum_type)
            for name, enum_type in zip(_STATE_FIELDS, enum_types)
        ):
            raise ValueError("INVALID_INITIAL_STATE")
        ok, errors = validate_state(initial_state)
        if not ok:
            raise ValueError(f"INVALID_INITIAL_STATE:{errors}")

        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS transition_engine_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL,
                    initial_state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transition_current_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transition_commits (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    spec_sha256 TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    target_state_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transition_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE
                        REFERENCES transition_commits(idempotency_key),
                    event_json TEXT NOT NULL
                );
                """
            )
            initial_json = _state_json(initial_state)
            self._db.execute("BEGIN IMMEDIATE")
            meta = self._db.execute(
                "SELECT schema_version, initial_state_json FROM transition_engine_meta WHERE singleton=1"
            ).fetchone()
            current = self._db.execute(
                "SELECT state_json FROM transition_current_state WHERE singleton=1"
            ).fetchone()
            if meta is None and current is None:
                self._db.execute(
                    "INSERT INTO transition_engine_meta(singleton,schema_version,initial_state_json) VALUES(1,?,?)",
                    (self.SCHEMA_VERSION, initial_json),
                )
                self._db.execute(
                    "INSERT INTO transition_current_state(singleton,state_json) VALUES(1,?)",
                    (initial_json,),
                )
            elif meta is None or current is None:
                raise RuntimeError("TRANSITION_STORE_CORRUPTED")
            elif meta[0] != self.SCHEMA_VERSION:
                raise RuntimeError("TRANSITION_STORE_SCHEMA_UNSUPPORTED")
            elif meta[1] != initial_json:
                raise ValueError("TRANSITION_INITIAL_STATE_CONFLICT")
            else:
                stored_state = _state_from_json(current[0])
                ok, errors = validate_state(stored_state)
                if not ok:
                    raise RuntimeError(f"TRANSITION_STORE_CORRUPTED:{errors}")
            self._db.commit()
        except BaseException:
            if self._db.in_transaction:
                self._db.rollback()
            self._db.close()
            raise

    def apply(self, spec: TransitionSpec) -> OrthogonalState:
        _validate_persistent_spec(spec)
        if not isinstance(spec.idempotency_key, str) or not spec.idempotency_key.strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        if spec.guard is not None:
            raise ValueError("PERSISTENT_GUARD_REQUIRES_DURABLE_CONTRACT")
        spec_json = _canonical_spec(spec)
        spec_hash = hashlib.sha256(spec_json.encode("utf-8")).hexdigest()
        source_json = _state_json(spec.source)
        target_json = _state_json(spec.target)

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT spec_sha256,spec_json,target_state_json FROM transition_commits WHERE idempotency_key=?",
                    (spec.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != spec_hash or existing[1] != spec_json:
                        raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                    audit = self._db.execute(
                        "SELECT event_json FROM transition_audit WHERE idempotency_key=?",
                        (spec.idempotency_key,),
                    ).fetchone()
                    if audit is None:
                        raise RuntimeError("TRANSITION_STORE_CORRUPTED")
                    try:
                        event = json.loads(audit[0])
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise RuntimeError("TRANSITION_STORE_CORRUPTED") from exc
                    if (
                        not isinstance(event, dict)
                        or event.get("idempotency_key") != spec.idempotency_key
                        or event.get("spec_sha256") != spec_hash
                    ):
                        raise RuntimeError("TRANSITION_STORE_CORRUPTED")
                    target = _state_from_json(existing[2])
                    target_ok, target_errors = validate_state(target)
                    if not target_ok:
                        raise RuntimeError(f"TRANSITION_STORE_CORRUPTED:{target_errors}")
                    self._db.commit()
                    return target

                source_ok, source_errors = validate_state(spec.source)
                if not source_ok:
                    raise ValueError(f"INVALID_SOURCE_STATE:{source_errors}")
                target_ok, target_errors = validate_state(spec.target)
                if not target_ok:
                    raise ValueError(f"INVALID_TARGET_STATE:{target_errors}")
                current = self._db.execute(
                    "SELECT state_json FROM transition_current_state WHERE singleton=1"
                ).fetchone()
                if current is None:
                    raise RuntimeError("TRANSITION_STORE_CORRUPTED")
                if current[0] != source_json:
                    raise ValueError("SOURCE_STATE_CONFLICT")
                if not _is_registered_transition(spec):
                    raise ValueError("UNDECLARED_TRANSITION")

                committed_at = datetime.now(timezone.utc).isoformat()
                event = {
                    "transition_id": spec.transition_id,
                    "action": spec.action,
                    "event_type": spec.audit_event_type,
                    "idempotency_key": spec.idempotency_key,
                    "spec_sha256": spec_hash,
                    "source": _state_document(spec.source),
                    "target": _state_document(spec.target),
                    "committed_at": committed_at,
                }
                self._db.execute(
                    "INSERT INTO transition_commits(idempotency_key,spec_sha256,spec_json,target_state_json,committed_at) VALUES(?,?,?,?,?)",
                    (spec.idempotency_key, spec_hash, spec_json, target_json, committed_at),
                )
                self._db.execute(
                    "INSERT INTO transition_audit(idempotency_key,event_json) VALUES(?,?)",
                    (spec.idempotency_key, json.dumps(event, sort_keys=True, separators=(",", ":"))),
                )
                self._db.execute(
                    "UPDATE transition_current_state SET state_json=? WHERE singleton=1 AND state_json=?",
                    (target_json, source_json),
                )
                if self._db.execute("SELECT changes()").fetchone()[0] != 1:
                    raise ValueError("SOURCE_STATE_CONFLICT")
                self._db.commit()
                return spec.target
            except BaseException:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    @property
    def current_state(self) -> OrthogonalState:
        with self._lock:
            row = self._db.execute(
                "SELECT state_json FROM transition_current_state WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise RuntimeError("TRANSITION_STORE_CORRUPTED")
            state = _state_from_json(row[0])
            ok, errors = validate_state(state)
            if not ok:
                raise RuntimeError(f"TRANSITION_STORE_CORRUPTED:{errors}")
            return state

    @property
    def audit(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT event_json FROM transition_audit ORDER BY sequence"
            ).fetchall()
            try:
                return tuple(json.loads(row[0]) for row in rows)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("TRANSITION_STORE_CORRUPTED") from exc

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "PersistentTransitionEngine":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

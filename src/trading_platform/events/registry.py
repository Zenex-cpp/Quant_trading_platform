from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


_REGISTRY_FIELDS = (
    "schema_id",
    "event_type",
    "version",
    "compatibility_mode",
    "producer",
    "consumer",
    "effective_from",
    "deprecation_date",
    "migration_reference",
    "payload_schema_ref",
)


@dataclass(frozen=True)
class EventSchemaRegistration:
    schema_id: str
    event_type: str
    version: str
    compatibility_mode: str
    producer: str
    consumer: str
    effective_from: str
    deprecation_date: str | None = None
    migration_reference: str | None = None
    payload_schema_ref: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "schema_id",
            "event_type",
            "version",
            "compatibility_mode",
            "producer",
            "consumer",
            "payload_schema_ref",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"EVENT_SCHEMA_FIELD_REQUIRED:{field_name}")
        if self.compatibility_mode != "NONE":
            raise ValueError("EVENT_SCHEMA_COMPATIBILITY_MODE_UNSUPPORTED")
        try:
            effective = date.fromisoformat(self.effective_from)
        except (TypeError, ValueError) as exc:
            raise ValueError("EVENT_SCHEMA_EFFECTIVE_DATE_INVALID") from exc
        if self.deprecation_date is not None:
            try:
                deprecated = date.fromisoformat(self.deprecation_date)
            except (TypeError, ValueError) as exc:
                raise ValueError("EVENT_SCHEMA_DEPRECATION_DATE_INVALID") from exc
            if deprecated < effective:
                raise ValueError("EVENT_SCHEMA_DEPRECATION_BEFORE_EFFECTIVE")
        if self.migration_reference is not None and not self.migration_reference.strip():
            raise ValueError("EVENT_SCHEMA_MIGRATION_REFERENCE_INVALID")


class EventSchemaRegistry:
    """Versioned event metadata and payload validation against local JSON Schemas."""

    def __init__(
        self,
        registrations: tuple[EventSchemaRegistration, ...] | list[EventSchemaRegistration] = (),
        *,
        schema_root: str | Path | None = None,
    ) -> None:
        self._schemas: dict[tuple[str, str], EventSchemaRegistration] = {}
        self._schema_ids: dict[str, EventSchemaRegistration] = {}
        self._schema_root = Path(schema_root).resolve() if schema_root is not None else None
        for registration in registrations:
            self.register(registration)

    @classmethod
    def from_csv(cls, path: str | Path) -> EventSchemaRegistry:
        registry_path = Path(path).resolve()
        try:
            with registry_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if tuple(reader.fieldnames or ()) != _REGISTRY_FIELDS:
                    raise ValueError("EVENT_SCHEMA_REGISTRY_COLUMNS_INVALID")
                registrations = []
                for row in reader:
                    if None in row:
                        raise ValueError("EVENT_SCHEMA_REGISTRY_ROW_INVALID")
                    registrations.append(
                        EventSchemaRegistration(
                            schema_id=row["schema_id"],
                            event_type=row["event_type"],
                            version=row["version"],
                            compatibility_mode=row["compatibility_mode"],
                            producer=row["producer"],
                            consumer=row["consumer"],
                            effective_from=row["effective_from"],
                            deprecation_date=row["deprecation_date"] or None,
                            migration_reference=row["migration_reference"] or None,
                            payload_schema_ref=row["payload_schema_ref"],
                        )
                    )
        except OSError as exc:
            raise ValueError("EVENT_SCHEMA_REGISTRY_UNREADABLE") from exc
        if not registrations:
            raise ValueError("EVENT_SCHEMA_REGISTRY_EMPTY")
        return cls(registrations, schema_root=registry_path.parent)

    @property
    def registrations(self) -> tuple[EventSchemaRegistration, ...]:
        return tuple(self._schemas[key] for key in sorted(self._schemas))

    def register(self, schema: EventSchemaRegistration) -> None:
        if not isinstance(schema, EventSchemaRegistration):
            raise TypeError("EVENT_SCHEMA_REGISTRATION_REQUIRED")
        key = (schema.event_type, schema.version)
        if key in self._schemas:
            raise ValueError("EVENT_SCHEMA_ALREADY_REGISTERED")
        if schema.schema_id in self._schema_ids:
            raise ValueError("EVENT_SCHEMA_ID_ALREADY_REGISTERED")
        self._schemas[key] = schema
        self._schema_ids[schema.schema_id] = schema

    def get(self, event_type: str, version: str) -> EventSchemaRegistration:
        try:
            return self._schemas[(event_type, version)]
        except KeyError as exc:
            raise KeyError(f"EVENT_SCHEMA_NOT_REGISTERED:{event_type}:{version}") from exc

    def get_by_id(self, schema_id: str) -> EventSchemaRegistration:
        try:
            return self._schema_ids[schema_id]
        except KeyError as exc:
            raise KeyError(f"EVENT_SCHEMA_ID_NOT_REGISTERED:{schema_id}") from exc

    def validate_event(self, event: Any) -> None:
        envelope = getattr(event, "envelope", None)
        if envelope is None or not hasattr(envelope, "validate"):
            raise ValueError("EVENT_ENVELOPE_REQUIRED")
        envelope.validate()
        registration = self.get(envelope.event_type, envelope.schema_version)
        envelope_schema_path = self._resolve_schema_path("v5_event_envelope.v1.schema.json")
        schema_path = self._resolve_schema_path(registration.payload_schema_ref)
        try:
            envelope_schema = json.loads(envelope_schema_path.read_text(encoding="utf-8"))
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("EVENT_SCHEMA_UNREADABLE") from exc
        self._assert_local_references(envelope_schema)
        self._assert_local_references(schema)
        Draft202012Validator.check_schema(envelope_schema)
        Draft202012Validator.check_schema(schema)

        envelope_mapping = _json_compatible(envelope)
        try:
            Draft202012Validator(envelope_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
                envelope_mapping
            )
        except ValidationError as exc:
            path = "/".join(str(part) for part in exc.absolute_path) or "$"
            raise ValueError(f"EVENT_ENVELOPE_SCHEMA_INVALID:{path}:{exc.validator}") from exc

        payload = _json_compatible(getattr(event, "payload", None))
        if not isinstance(payload, Mapping):
            raise ValueError("EVENT_PAYLOAD_OBJECT_REQUIRED")
        payload_event_type = payload.get("event_type")
        if payload_event_type is not None and payload_event_type != envelope.event_type.rsplit(".", 1)[-1]:
            raise ValueError("EVENT_PAYLOAD_TYPE_MISMATCH")
        try:
            Draft202012Validator(schema).validate(payload)
        except ValidationError as exc:
            path = "/".join(str(part) for part in exc.absolute_path) or "$"
            raise ValueError(f"EVENT_PAYLOAD_SCHEMA_INVALID:{path}:{exc.validator}") from exc

    def _resolve_schema_path(self, reference: str) -> Path:
        if self._schema_root is None:
            raise ValueError("EVENT_SCHEMA_ROOT_REQUIRED")
        candidate = (self._schema_root / reference).resolve()
        try:
            candidate.relative_to(self._schema_root)
        except ValueError as exc:
            raise ValueError("EVENT_PAYLOAD_SCHEMA_PATH_OUTSIDE_ROOT") from exc
        if not candidate.is_file():
            raise ValueError("EVENT_PAYLOAD_SCHEMA_NOT_FOUND")
        return candidate

    @classmethod
    def _assert_local_references(cls, value: Any) -> None:
        if isinstance(value, Mapping):
            reference = value.get("$ref")
            if reference is not None and (
                not isinstance(reference, str) or not reference.startswith("#/")
            ):
                raise ValueError("EVENT_PAYLOAD_SCHEMA_EXTERNAL_REFERENCE_FORBIDDEN")
            for nested in value.values():
                cls._assert_local_references(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._assert_local_references(nested)


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_compatible(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_compatible(asdict(value))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("EVENT_PAYLOAD_MAPPING_KEYS_MUST_BE_STRINGS")
        return {key: _json_compatible(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_compatible(nested) for nested in value]
    raise ValueError("EVENT_PAYLOAD_NOT_JSON_COMPATIBLE")

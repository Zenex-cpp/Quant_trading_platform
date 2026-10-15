from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from trading_platform.portfolio.config import ConfigValue, Precedence, resolve_config
from trading_platform.v21.event_store import EventStore


class ConfigurationAuthorityError(RuntimeError):
    pass


class ConfigurationAuthorityConflict(ConfigurationAuthorityError):
    pass


class ConfigurationResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CONFIG_CONFLICT = "CONFIG_CONFLICT"


def _hash(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256(body.encode("utf-8")).hexdigest()


def candidate_fingerprint(values: Iterable[ConfigValue]) -> str:
    canonical = sorted(
        (
            {
                "name": value.name,
                "value_fingerprint": _hash({"value": value.value}),
                "precedence": int(value.precedence),
                "source": value.source,
                "version": value.version,
                "immutable": bool(value.immutable),
            }
            for value in values
        ),
        key=lambda item: (item["name"], item["precedence"], item["source"], item["version"], item["value_fingerprint"]),
    )
    return _hash({"candidates": canonical})


@dataclass(frozen=True)
class ConfigurationResolution:
    resolution_id: str
    config_name: str
    status: ConfigurationResolutionStatus
    selected_source: str
    selected_version: str
    selected_value_fingerprint: str
    candidates_fingerprint: str
    valid_from: datetime
    expires_at: datetime
    operator: str
    recorded_at_ms: int

    @property
    def fingerprint(self) -> str:
        return _hash({
            "resolution_id": self.resolution_id,
            "config_name": self.config_name,
            "status": self.status.value,
            "selected_source": self.selected_source,
            "selected_version": self.selected_version,
            "selected_value_fingerprint": self.selected_value_fingerprint,
            "candidates_fingerprint": self.candidates_fingerprint,
            "valid_from": self.valid_from.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "operator": self.operator,
            "recorded_at_ms": self.recorded_at_ms,
        })


class ConfigurationAuthorityLedger:
    """Durable configuration-resolution authority for live decisions.

    Equal-precedence conflicting values are recorded as a durable BLOCK state and
    can never authorize a LIVE trade/deployment decision. Raw configuration values
    are never persisted; only deterministic fingerprints and provenance are stored.
    """

    RECORDED_EVENT = "CONFIGURATION_RESOLUTION_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ConfigurationAuthorityError(f"CONFIGURATION_{field}_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _payload_from_record(cls, record: ConfigurationResolution) -> dict[str, Any]:
        return {
            "resolution_id": record.resolution_id,
            "config_name": record.config_name,
            "status": record.status.value,
            "selected_source": record.selected_source,
            "selected_version": record.selected_version,
            "selected_value_fingerprint": record.selected_value_fingerprint,
            "candidates_fingerprint": record.candidates_fingerprint,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "operator": record.operator,
            "recorded_at_ms": record.recorded_at_ms,
        }

    @classmethod
    def _from_event(cls, event) -> ConfigurationResolution:
        try:
            record = ConfigurationResolution(
                resolution_id=str(event.payload["resolution_id"]),
                config_name=str(event.payload["config_name"]),
                status=ConfigurationResolutionStatus(str(event.payload["status"])),
                selected_source=str(event.payload["selected_source"]),
                selected_version=str(event.payload["selected_version"]),
                selected_value_fingerprint=str(event.payload["selected_value_fingerprint"]),
                candidates_fingerprint=str(event.payload["candidates_fingerprint"]),
                valid_from=datetime.fromisoformat(str(event.payload["valid_from"])).astimezone(timezone.utc),
                expires_at=datetime.fromisoformat(str(event.payload["expires_at"])).astimezone(timezone.utc),
                operator=str(event.payload["operator"]),
                recorded_at_ms=int(event.payload["recorded_at_ms"]),
            )
        except Exception as exc:
            raise ConfigurationAuthorityError("INVALID_CONFIGURATION_RESOLUTION_PAYLOAD") from exc
        if not record.resolution_id or not record.config_name or not record.operator:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_FIELDS_REQUIRED")
        if record.expires_at <= record.valid_from:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_WINDOW_INVALID")
        if record.recorded_at_ms < 0:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_TIMESTAMP_INVALID")
        return record

    def record(
        self,
        *,
        resolution_id: str,
        config_name: str,
        values: Iterable[ConfigValue],
        valid_from: datetime,
        expires_at: datetime,
        operator: str = "system",
        recorded_at_ms: int,
    ) -> tuple[ConfigurationResolution, bool]:
        values_tuple = tuple(values)
        if not resolution_id or not config_name or not operator:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_IDENTIFIERS_REQUIRED")
        if not values_tuple:
            raise ConfigurationAuthorityError("CONFIGURATION_VALUES_REQUIRED")
        if valid_from.tzinfo is None or expires_at.tzinfo is None or expires_at <= valid_from:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_WINDOW_INVALID")
        if recorded_at_ms < 0:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_TIMESTAMP_INVALID")
        if any(value.name != config_name for value in values_tuple):
            raise ConfigurationAuthorityError("CONFIGURATION_NAME_MISMATCH")
        if not self.store.verify_chain():
            raise ConfigurationAuthorityError("CONFIGURATION_EVENT_CHAIN_INVALID")

        candidates_fp = candidate_fingerprint(values_tuple)
        try:
            selected = resolve_config(list(values_tuple))
        except ValueError as exc:
            if str(exc) != "CONFIG_CONFLICT":
                raise
            record = ConfigurationResolution(
                resolution_id=resolution_id,
                config_name=config_name,
                status=ConfigurationResolutionStatus.CONFIG_CONFLICT,
                selected_source="",
                selected_version="",
                selected_value_fingerprint="",
                candidates_fingerprint=candidates_fp,
                valid_from=valid_from.astimezone(timezone.utc),
                expires_at=expires_at.astimezone(timezone.utc),
                operator=operator,
                recorded_at_ms=recorded_at_ms,
            )
        else:
            record = ConfigurationResolution(
                resolution_id=resolution_id,
                config_name=config_name,
                status=ConfigurationResolutionStatus.RESOLVED,
                selected_source=selected.source,
                selected_version=selected.version,
                selected_value_fingerprint=_hash({"value": selected.value}),
                candidates_fingerprint=candidates_fp,
                valid_from=valid_from.astimezone(timezone.utc),
                expires_at=expires_at.astimezone(timezone.utc),
                operator=operator,
                recorded_at_ms=recorded_at_ms,
            )

        payload = self._payload_from_record(record)
        event_id = f"configuration-resolution:{resolution_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED_EVENT or _hash(existing.payload) != _hash(payload):
                raise ConfigurationAuthorityConflict("CONFIGURATION_RESOLUTION_ID_CONFLICT")
            return self._from_event(existing), False
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=self.RECORDED_EVENT,
                aggregate_id=config_name,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = self.store.get(event_id)
            if existing is None:
                raise ConfigurationAuthorityError("CONFIGURATION_CONCURRENT_APPEND_UNRESOLVED") from exc
            if existing.event_type != self.RECORDED_EVENT or _hash(existing.payload) != _hash(payload):
                raise ConfigurationAuthorityConflict("CONFIGURATION_CONCURRENT_CONFLICT") from exc
            return self._from_event(existing), False
        if not self.store.verify_chain():
            raise ConfigurationAuthorityError("CONFIGURATION_EVENT_CHAIN_INVALID_AFTER_APPEND")
        return self._from_event(result.event), not result.duplicate

    def get(self, resolution_id: str) -> ConfigurationResolution | None:
        if not self.store.verify_chain():
            raise ConfigurationAuthorityError("CONFIGURATION_EVENT_CHAIN_INVALID")
        event = self.store.get(f"configuration-resolution:{resolution_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED_EVENT:
            raise ConfigurationAuthorityError("CONFIGURATION_EVENT_TYPE_MISMATCH")
        record = self._from_event(event)
        if record.resolution_id != resolution_id:
            raise ConfigurationAuthorityConflict("CONFIGURATION_RESOLUTION_ID_MISMATCH")
        return record

    def assert_live_safe(
        self,
        resolution_id: str,
        *,
        now: datetime,
        expected_candidates_fingerprint: str | None = None,
    ) -> ConfigurationResolution:
        record = self.get(resolution_id)
        if record is None:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_NOT_FOUND")
        if now.tzinfo is None:
            raise ConfigurationAuthorityError("CONFIGURATION_NOW_TIMEZONE_REQUIRED")
        now = now.astimezone(timezone.utc)
        if now < record.valid_from or now >= record.expires_at:
            raise ConfigurationAuthorityError("CONFIGURATION_RESOLUTION_EXPIRED")
        if record.status is not ConfigurationResolutionStatus.RESOLVED:
            raise ConfigurationAuthorityError("CONFIG_CONFLICT")
        if expected_candidates_fingerprint is not None and record.candidates_fingerprint != expected_candidates_fingerprint:
            raise ConfigurationAuthorityConflict("CONFIGURATION_FINGERPRINT_MISMATCH")
        return record

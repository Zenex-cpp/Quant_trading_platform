from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from trading_platform.events import Event, EventEnvelope, EventSchemaRegistry, EventSchemaRegistration
from trading_platform.realtime import EventEnvelope as RealtimeEventEnvelope
from trading_platform.v27.governance import GovernanceEvent, GovernanceEventType
from trading_platform.v28.deployment import (
    DeploymentEvent,
    DeploymentEventType,
    DeploymentPhase,
)
from trading_platform.v29.provenance import ProvenanceEvent, ProvenanceEventType


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "schemas/v5_event_schema_registry.csv"


def _registry() -> EventSchemaRegistry:
    return EventSchemaRegistry.from_csv(REGISTRY_PATH)


def _envelope(event_type: str, *, event_time: datetime | None = None) -> EventEnvelope:
    event_time = event_time or datetime(2026, 11, 12, 10, tzinfo=timezone.utc)
    return EventEnvelope(
        event_id="delivery-1",
        event_type=event_type,
        event_version="1.0",
        schema_version="1.0",
        event_time=event_time,
        receive_time=event_time + timedelta(milliseconds=1),
        processing_time=event_time + timedelta(milliseconds=2),
        source="tests",
        correlation_id="corr-1",
        sequence_number=1,
    )


def test_v5_event_registry_covers_all_typed_governance_deployment_and_provenance_events():
    registry = _registry()
    registered = {item.event_type for item in registry.registrations}
    expected = {
        *(f"governance.{item.value}" for item in GovernanceEventType),
        *(f"deployment.{item.value}" for item in DeploymentEventType),
        *(f"provenance.{item.value}" for item in ProvenanceEventType),
    }

    assert len(registry.registrations) == 19
    assert registered == expected
    assert len({item.schema_id for item in registry.registrations}) == 19
    assert all(item.version == "1.0" for item in registry.registrations)
    assert all(item.compatibility_mode == "NONE" for item in registry.registrations)
    for registration in registry.registrations:
        assert registry.get_by_id(registration.schema_id) == registration
        schema = json.loads((ROOT / "schemas" / registration.payload_schema_ref).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_v5_event_payload_schemas_match_the_typed_event_models():
    expected = {
        "governance": (GovernanceEvent, GovernanceEventType),
        "deployment": (DeploymentEvent, DeploymentEventType),
        "provenance": (ProvenanceEvent, ProvenanceEventType),
    }
    for domain, (event_model, event_types) in expected.items():
        schema_path = ROOT / f"schemas/v5_event_payload_schemas/{domain}.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == {field.name for field in fields(event_model)}
        assert set(schema["required"]) == {field.name for field in fields(event_model)}
        assert set(schema["properties"]["event_type"]["enum"]) == {item.value for item in event_types}


def test_v5_event_registry_validates_a_real_governance_payload_and_rejects_invalid_payloads():
    payload = GovernanceEvent.build(
        sequence=1,
        event_type=GovernanceEventType.PROMOTION,
        actor="operator-1",
        model_id="model-2",
        previous_model_id="model-1",
        reason="PROMOTION_VALIDATED",
        risk_before=Decimal("10"),
        risk_after=Decimal("10"),
        timestamp_ns=1_000,
    )
    Event(_envelope("governance.PROMOTION"), payload).validate(_registry())

    invalid_payload = {
        "event_id": "id-1",
        "sequence": 1,
        "event_type": "PROMOTION",
        "actor": "",
        "model_id": "model-2",
        "previous_model_id": None,
        "reason": "PROMOTION_VALIDATED",
        "risk_before": "10",
        "risk_after": "10",
        "timestamp_ns": 1_000,
        "previous_hash": "GENESIS",
        "event_hash": "a" * 64,
    }
    with pytest.raises(ValueError, match="EVENT_PAYLOAD_SCHEMA_INVALID:actor:minLength"):
        Event(_envelope("governance.PROMOTION"), invalid_payload).validate(_registry())


def test_v5_event_registry_rejects_mismatched_type_version_and_unsafe_schema_paths():
    payload = {
        "event_id": "id-1",
        "sequence": 1,
        "event_type": "DEMOTION",
        "actor": "operator-1",
        "model_id": "model-2",
        "previous_model_id": None,
        "reason": "reason",
        "risk_before": "10",
        "risk_after": "0",
        "timestamp_ns": 1_000,
        "previous_hash": "GENESIS",
        "event_hash": "a" * 64,
    }
    with pytest.raises(ValueError, match="EVENT_PAYLOAD_TYPE_MISMATCH"):
        Event(_envelope("governance.PROMOTION"), payload).validate(_registry())

    with pytest.raises(KeyError, match="EVENT_SCHEMA_NOT_REGISTERED"):
        Event(
            EventEnvelope(
                **{**_envelope("governance.PROMOTION").__dict__, "schema_version": "2.0"}
            ),
            payload,
        ).validate(_registry())

    outside = EventSchemaRegistration(
        schema_id="outside.v1",
        event_type="outside.EVENT",
        version="1.0",
        compatibility_mode="NONE",
        producer="tests",
        consumer="tests",
        effective_from="2026-11-12",
        payload_schema_ref="../outside.json",
    )
    unsafe_registry = EventSchemaRegistry((outside,), schema_root=ROOT / "schemas")
    with pytest.raises(ValueError, match="EVENT_PAYLOAD_SCHEMA_PATH_OUTSIDE_ROOT"):
        Event(_envelope("outside.EVENT"), {}).validate(unsafe_registry)


def test_v5_event_registry_rejects_duplicate_identity_and_unimplemented_compatibility_modes():
    registration = EventSchemaRegistration(
        schema_id="test.EVENT.v1",
        event_type="test.EVENT",
        version="1.0",
        compatibility_mode="NONE",
        producer="tests",
        consumer="tests",
        effective_from="2026-11-12",
        payload_schema_ref="event.json",
    )
    with pytest.raises(ValueError, match="EVENT_SCHEMA_ALREADY_REGISTERED"):
        EventSchemaRegistry((registration, registration))
    with pytest.raises(ValueError, match="EVENT_SCHEMA_COMPATIBILITY_MODE_UNSUPPORTED"):
        EventSchemaRegistration(
            schema_id="test.EVENT.v2",
            event_type="test.EVENT",
            version="2.0",
            compatibility_mode="BACKWARD",
            producer="tests",
            consumer="tests",
            effective_from="2026-11-12",
            payload_schema_ref="event.json",
        )


def test_v5_event_envelope_is_shared_with_realtime_and_fails_closed_on_invalid_timing():
    assert RealtimeEventEnvelope is EventEnvelope
    event = _envelope("market.TRADE")
    event.validate()
    with pytest.raises(ValueError, match="EVENT_TIMEZONE_REQUIRED"):
        EventEnvelope(
            event_id="id",
            event_type="market.TRADE",
            event_version="1.0",
            schema_version="1.0",
            event_time=datetime(2026, 11, 12),
            receive_time=datetime(2026, 11, 12, tzinfo=timezone.utc),
            processing_time=datetime(2026, 11, 12, tzinfo=timezone.utc),
            source="test",
        ).validate()
    with pytest.raises(ValueError, match="RECEIVE_BEFORE_EVENT_TIME"):
        EventEnvelope(
            event_id="id",
            event_type="market.TRADE",
            event_version="1.0",
            schema_version="1.0",
            event_time=datetime(2026, 11, 12, 10, tzinfo=timezone.utc),
            receive_time=datetime(2026, 11, 12, 9, tzinfo=timezone.utc),
            processing_time=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
            source="test",
        ).validate()

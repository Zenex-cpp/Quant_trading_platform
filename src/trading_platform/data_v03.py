"""V0.3 data integrity, point-in-time, leakage and lineage contracts."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable


class QualityStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    CRITICAL = "CRITICAL"


class UnknownSemantics(str, Enum):
    NULL = "NULL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_PROVIDED = "NOT_PROVIDED"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"


@dataclass(frozen=True)
class Availability:
    available_at: datetime
    availability_source: str
    publication_delay_ms: int
    revision_policy: str

    def validate(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("AVAILABILITY_TIMEZONE_REQUIRED")
        if self.publication_delay_ms < 0:
            raise ValueError("NEGATIVE_PUBLICATION_DELAY")


@dataclass(frozen=True)
class DataVersion:
    first_published_version: str
    revised_version: str | None
    revision_timestamp: datetime | None
    as_of_availability: datetime

    def validate(self) -> None:
        if self.as_of_availability.tzinfo is None:
            raise ValueError("AS_OF_TIMEZONE_REQUIRED")
        if self.revision_timestamp is not None and self.revision_timestamp.tzinfo is None:
            raise ValueError("REVISION_TIMEZONE_REQUIRED")


@dataclass(frozen=True)
class DatasetContract:
    dataset_id: str
    dataset_version: str
    schema_version: str
    source: str
    snapshot_id: str
    lineage: tuple[str, ...]
    content_hash: str
    schema_hash: str
    coverage_start: datetime
    coverage_end: datetime
    quality_status: QualityStatus
    quality_report: str
    retention_policy: str
    ingestion_time: datetime

    def validate(self) -> None:
        if self.coverage_start.tzinfo is None or self.coverage_end.tzinfo is None or self.ingestion_time.tzinfo is None:
            raise ValueError("DATASET_TIMEZONE_REQUIRED")
        if self.coverage_start >= self.coverage_end:
            raise ValueError("INVALID_COVERAGE")
        if not self.content_hash or not self.schema_hash:
            raise ValueError("DATASET_HASH_REQUIRED")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(records: Iterable[Any]) -> str:
    payload = canonical_json(list(records)).encode()
    return sha256(payload).hexdigest()


def assert_point_in_time(*, feature_available_at: datetime, event_time: datetime, prediction_time: datetime) -> None:
    for x in (feature_available_at, event_time, prediction_time):
        if x.tzinfo is None:
            raise ValueError("PIT_TIMEZONE_REQUIRED")
    if feature_available_at > prediction_time:
        raise ValueError("POINT_IN_TIME_LEAKAGE")
    if event_time > prediction_time:
        raise ValueError("FUTURE_EVENT_LEAKAGE")


def assert_available_before(*, available_at: datetime, consumer_time: datetime) -> None:
    if available_at.tzinfo is None or consumer_time.tzinfo is None:
        raise ValueError("PIT_TIMEZONE_REQUIRED")
    if available_at > consumer_time:
        raise ValueError("NOT_YET_AVAILABLE_AT_CONSUMPTION")


def assert_as_of_version(*, data: DataVersion, consumer_time: datetime) -> None:
    data.validate()
    if consumer_time.tzinfo is None:
        raise ValueError("PIT_TIMEZONE_REQUIRED")
    if data.as_of_availability > consumer_time:
        raise ValueError("RETROACTIVE_REVISION_LEAKAGE")


@dataclass(frozen=True)
class FeatureProvenance:
    feature_id: str
    feature_version: str
    hypothesis: str
    definition: str
    source_ids: tuple[str, ...]
    availability: Availability
    window: str
    implementation_version: str
    validation_status: QualityStatus
    lineage: tuple[str, ...]


@dataclass(frozen=True)
class TargetContract:
    target_id: str
    version: str
    horizon: str
    entry_definition: str
    exit_definition: str
    cost_assumption: str
    labeling_method: str
    overlap_policy: str
    class_balance: str
    missing_label_policy: str


@dataclass(frozen=True)
class LeakageFinding:
    finding_id: str
    category: str
    severity: str
    object_id: str
    evidence: str
    remediation: str
    detected_at: datetime


LEAKAGE_CATEGORIES = (
    "FEATURE_LEAKAGE", "TARGET_LEAKAGE", "TIMESTAMP_LEAKAGE", "NORMALIZATION_LEAKAGE",
    "TRAIN_TEST_OVERLAP", "LABEL_OVERLAP", "DUPLICATED_OBSERVATION", "SURVIVORSHIP_BIAS",
    "DELISTING_BIAS", "REVISION_LEAKAGE", "CORPORATE_ACTION_LOOKAHEAD", "TIMEZONE_DST",
    "CROSS_ASSET_FUTURE_INFORMATION", "SELECTION_LEAKAGE"
)


def scan_duplicate_observations(records: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[LeakageFinding]:
    seen: dict[tuple[Any, ...], int] = {}
    findings: list[LeakageFinding] = []
    for i, row in enumerate(records):
        key = tuple(row.get(k) for k in key_fields)
        if key in seen:
            findings.append(LeakageFinding(
                finding_id=f"dup:{i}", category="DUPLICATED_OBSERVATION", severity="HIGH",
                object_id=str(i), evidence=f"duplicate_of={seen[key]}",
                remediation="deduplicate before split or invalidate duplicate lineage",
                detected_at=datetime.now(timezone.utc)))
        else:
            seen[key] = i
    return findings


def validate_temporal_order(rows: list[dict[str, Any]], event_time_field: str = "event_time") -> None:
    previous: datetime | None = None
    for row in rows:
        current = row[event_time_field]
        if current.tzinfo is None:
            raise ValueError("TEMPORAL_ORDER_TIMEZONE_REQUIRED")
        if previous is not None and current < previous:
            raise ValueError("OUT_OF_ORDER_DATA")
        previous = current

"""V0.4 model/input/output execution contracts."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(obj: Any) -> str:
    return sha256(canonical(obj).encode()).hexdigest()


@dataclass(frozen=True)
class SchemaContract:
    schema_id: str
    version: str
    fields: tuple[str, ...]

    def validate_keys(self, obj: Mapping[str, Any]) -> None:
        missing = [f for f in self.fields if f not in obj]
        if missing:
            raise ValueError(f"SCHEMA_MISMATCH:missing={missing}")


@dataclass(frozen=True)
class ModelArtifactContract:
    model_id: str
    model_version: str
    artifact_hash: str
    model_input_schema: SchemaContract
    model_output_schema: SchemaContract
    feature_version: str
    runtime_compatibility: str
    dependency_compatibility: str
    configuration_compatibility: str

    def pre_load_validate(self, *, actual_hash: str, feature_version: str,
                          runtime_compatibility: str, dependency_compatibility: str,
                          configuration_compatibility: str) -> None:
        if actual_hash != self.artifact_hash:
            raise ValueError("ARTIFACT_INTEGRITY_FAILURE")
        if feature_version != self.feature_version:
            raise ValueError("FEATURE_VERSION_INCOMPATIBLE")
        if runtime_compatibility != self.runtime_compatibility:
            raise ValueError("RUNTIME_INCOMPATIBLE")
        if dependency_compatibility != self.dependency_compatibility:
            raise ValueError("DEPENDENCY_INCOMPATIBLE")
        if configuration_compatibility != self.configuration_compatibility:
            raise ValueError("CONFIGURATION_INCOMPATIBLE")


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    model_id: str
    model_version: str
    timestamp: datetime
    feature_version: str
    target_version: str
    prediction: float
    probability: float | None
    expected_return: float | None
    expected_risk: float | None
    uncertainty: float
    calibration_state: str
    valid_from: datetime
    expires_at: datetime

    def validate(self) -> None:
        if self.timestamp.tzinfo is None or self.valid_from.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("PREDICTION_TIMEZONE_REQUIRED")
        if self.expires_at <= self.valid_from:
            raise ValueError("INVALID_PREDICTION_TTL")
        if self.uncertainty < 0:
            raise ValueError("NEGATIVE_UNCERTAINTY")
        if not (-1e-15 <= self.prediction <= 1 + 1e-15):
            # Prediction itself is allowed to be a score, but probabilities are not.
            pass
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise ValueError("INVALID_PROBABILITY")

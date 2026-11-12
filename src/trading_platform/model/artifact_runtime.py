"""Bounded, signature-checked runtime for portable linear-logit artifacts.

The loader accepts a deliberately small JSON model format and never imports or
deserializes executable Python objects. Signatures cover the exact artifact
bytes; callers must supply the public key from their configured trust policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.model.contracts import (
    ModelArtifactContract,
    Prediction,
    SchemaContract,
    stable_hash,
)


MAX_SIGNED_MODEL_BYTES = 2 * 1024 * 1024
MAX_PREDICTION_TTL_SECONDS = 7 * 24 * 60 * 60
ARTIFACT_TYPE = "TRADING_PLATFORM_LINEAR_LOGIT_V1"
_PREDICTION_FIELDS = frozenset({
    "prediction_id",
    "model_id",
    "model_version",
    "timestamp",
    "feature_version",
    "target_version",
    "prediction",
    "probability",
    "expected_return",
    "expected_risk",
    "uncertainty",
    "calibration_state",
    "valid_from",
    "expires_at",
})


class ModelArtifactLoadError(ValueError):
    """An artifact failed bounded parsing, signature, integrity, or contract checks."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelArtifactLoadError("MODEL_ARTIFACT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonstandard_json(value: str) -> None:
    raise ModelArtifactLoadError("MODEL_ARTIFACT_NONFINITE_JSON_NUMBER")


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ModelArtifactLoadError(f"MODEL_ARTIFACT_{field}_NUMBER_REQUIRED")
    result = float(value)
    if not math.isfinite(result):
        raise ModelArtifactLoadError(f"MODEL_ARTIFACT_{field}_FINITE_REQUIRED")
    return result


def _schema(payload: Any, field: str) -> SchemaContract:
    if not isinstance(payload, dict) or set(payload) != {"schema_id", "version", "fields"}:
        raise ModelArtifactLoadError(f"MODEL_ARTIFACT_{field}_SCHEMA_INVALID")
    schema_id = payload["schema_id"]
    version = payload["version"]
    fields = payload["fields"]
    if (
        not isinstance(schema_id, str)
        or not schema_id
        or not isinstance(version, str)
        or not version
        or not isinstance(fields, list)
        or not fields
        or any(not isinstance(item, str) or not item for item in fields)
        or len(fields) != len(set(fields))
    ):
        raise ModelArtifactLoadError(f"MODEL_ARTIFACT_{field}_SCHEMA_INVALID")
    return SchemaContract(schema_id, version, tuple(fields))


@dataclass(frozen=True)
class SignedLinearModelV1:
    """Immutable logistic model implementing the V3.73 prediction-stage seam."""

    contract: ModelArtifactContract
    target_version: str
    coefficients: tuple[float, ...]
    intercept: float
    uncertainty: float
    calibration_state: str
    prediction_ttl_seconds: int
    artifact_hash: str

    def _feature_vector(self, features: Mapping[str, Any]) -> tuple[float, ...]:
        if not isinstance(features, Mapping):
            raise ModelArtifactLoadError("MODEL_FEATURE_MAPPING_REQUIRED")
        expected = self.contract.model_input_schema.fields
        if set(features) != set(expected):
            raise ModelArtifactLoadError("MODEL_FEATURE_SCHEMA_MISMATCH")
        return tuple(_finite_number(features[field], "FEATURE") for field in expected)

    def predict(
        self,
        features: Mapping[str, Any],
        *,
        timestamp: datetime,
    ) -> Prediction:
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ModelArtifactLoadError("MODEL_PREDICTION_TIMEZONE_REQUIRED")
        vector = self._feature_vector(features)
        logit = self.intercept + sum(weight * value for weight, value in zip(self.coefficients, vector))
        if not math.isfinite(logit):
            raise ModelArtifactLoadError("MODEL_LOGIT_NONFINITE")
        if logit >= 0:
            probability = 1.0 / (1.0 + math.exp(-min(logit, 709.0)))
        else:
            exp_logit = math.exp(max(logit, -709.0))
            probability = exp_logit / (1.0 + exp_logit)
        normalized_features = {
            name: value for name, value in zip(self.contract.model_input_schema.fields, vector)
        }
        prediction_id = stable_hash({
            "artifact_hash": self.artifact_hash,
            "model_id": self.contract.model_id,
            "model_version": self.contract.model_version,
            "timestamp": timestamp.isoformat(),
            "feature_version": self.contract.feature_version,
            "target_version": self.target_version,
            "features": normalized_features,
        })
        valid_from = timestamp
        expires_at = timestamp + timedelta(seconds=self.prediction_ttl_seconds)
        prediction = Prediction(
            prediction_id=prediction_id,
            model_id=self.contract.model_id,
            model_version=self.contract.model_version,
            timestamp=timestamp,
            feature_version=self.contract.feature_version,
            target_version=self.target_version,
            prediction=probability,
            probability=probability,
            expected_return=None,
            expected_risk=self.uncertainty,
            uncertainty=self.uncertainty,
            calibration_state=self.calibration_state,
            valid_from=valid_from,
            expires_at=expires_at,
            artifact_hash=self.artifact_hash,
            uncertainty_method="SIGNED_MODEL_DECLARED",
            uncertainty_source="SIGNED_MODEL_ARTIFACT_HASH_AND_PREDICTION_ID",
        )
        prediction.validate()
        return prediction

    def __call__(self, event: Any, features: Mapping[str, Any], regime: Any = None) -> Prediction:
        """Adapt this immutable artifact to BacktestStageFunctions.prediction_fn."""
        del regime
        timestamp = getattr(event, "event_time", None)
        return self.predict(features, timestamp=timestamp)


def load_signed_linear_model_v1(
    artifact_bytes: bytes,
    *,
    signature: bytes,
    trusted_public_key: bytes,
    contract: ModelArtifactContract,
    target_version: str,
    actual_feature_version: str,
    actual_runtime_compatibility: str,
    actual_dependency_compatibility: str,
    actual_configuration_compatibility: str,
) -> SignedLinearModelV1:
    """Verify and load one bounded Ed25519-signed, non-executable JSON model."""
    if not isinstance(artifact_bytes, bytes) or not artifact_bytes:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_BYTES_REQUIRED")
    if len(artifact_bytes) > MAX_SIGNED_MODEL_BYTES:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_SIZE_LIMIT_EXCEEDED")
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_SIGNATURE_INVALID")
    if not isinstance(trusted_public_key, bytes) or len(trusted_public_key) != 32:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_TRUSTED_KEY_INVALID")
    try:
        verifier = Ed25519PublicKey.from_public_bytes(trusted_public_key)
        verifier.verify(signature, artifact_bytes)
    except InvalidSignature as exc:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_SIGNATURE_INVALID") from exc
    except ValueError as exc:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_TRUSTED_KEY_INVALID") from exc

    artifact_hash = sha256(artifact_bytes).hexdigest()
    try:
        contract.pre_load_validate(
            actual_hash=artifact_hash,
            feature_version=actual_feature_version,
            runtime_compatibility=actual_runtime_compatibility,
            dependency_compatibility=actual_dependency_compatibility,
            configuration_compatibility=actual_configuration_compatibility,
        )
    except ValueError as exc:
        raise ModelArtifactLoadError(str(exc)) from exc

    try:
        payload = json.loads(
            artifact_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_json,
        )
    except ModelArtifactLoadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_JSON_INVALID") from exc

    required_fields = {
        "artifact_type",
        "model_id",
        "model_version",
        "model_input_schema",
        "model_output_schema",
        "feature_version",
        "target_version",
        "runtime_compatibility",
        "dependency_compatibility",
        "configuration_compatibility",
        "coefficients",
        "intercept",
        "uncertainty",
        "calibration_state",
        "prediction_ttl_seconds",
    }
    if not isinstance(payload, dict) or set(payload) != required_fields:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_FIELDS_INVALID")
    if payload["artifact_type"] != ARTIFACT_TYPE:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_TYPE_UNSUPPORTED")
    if payload["model_id"] != contract.model_id:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_ID_MISMATCH")
    if payload["model_version"] != contract.model_version:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_VERSION_MISMATCH")
    if payload["feature_version"] != contract.feature_version:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_FEATURE_VERSION_MISMATCH")
    if payload["target_version"] != target_version or not target_version:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_TARGET_VERSION_MISMATCH")
    for field, expected in (
        ("runtime_compatibility", contract.runtime_compatibility),
        ("dependency_compatibility", contract.dependency_compatibility),
        ("configuration_compatibility", contract.configuration_compatibility),
    ):
        if payload[field] != expected:
            raise ModelArtifactLoadError(f"MODEL_ARTIFACT_{field.upper()}_MISMATCH")

    input_schema = _schema(payload["model_input_schema"], "INPUT")
    output_schema = _schema(payload["model_output_schema"], "OUTPUT")
    if input_schema != contract.model_input_schema:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_INPUT_SCHEMA_MISMATCH")
    if output_schema != contract.model_output_schema:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_OUTPUT_SCHEMA_MISMATCH")
    if not _PREDICTION_FIELDS.issubset(output_schema.fields):
        raise ModelArtifactLoadError("MODEL_ARTIFACT_OUTPUT_SCHEMA_INCOMPLETE")

    coefficients_payload = payload["coefficients"]
    if not isinstance(coefficients_payload, dict) or set(coefficients_payload) != set(input_schema.fields):
        raise ModelArtifactLoadError("MODEL_ARTIFACT_COEFFICIENT_SCHEMA_MISMATCH")
    coefficients = tuple(
        _finite_number(coefficients_payload[name], "COEFFICIENT")
        for name in input_schema.fields
    )
    intercept = _finite_number(payload["intercept"], "INTERCEPT")
    uncertainty = _finite_number(payload["uncertainty"], "UNCERTAINTY")
    if not 0.0 <= uncertainty <= 1.0:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_UNCERTAINTY_INVALID")
    calibration_state = payload["calibration_state"]
    if calibration_state not in {"CALIBRATED", "ACCEPTABLE", "POOR", "UNKNOWN"}:
        raise ModelArtifactLoadError("MODEL_ARTIFACT_CALIBRATION_STATE_INVALID")
    ttl = payload["prediction_ttl_seconds"]
    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or ttl < 1
        or ttl > MAX_PREDICTION_TTL_SECONDS
    ):
        raise ModelArtifactLoadError("MODEL_ARTIFACT_PREDICTION_TTL_INVALID")

    return SignedLinearModelV1(
        contract=contract,
        target_version=target_version,
        coefficients=coefficients,
        intercept=intercept,
        uncertainty=uncertainty,
        calibration_state=calibration_state,
        prediction_ttl_seconds=ttl,
        artifact_hash=artifact_hash,
    )

"""Source-bound uncertainty evidence derived from one signed model prediction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from trading_platform.model.calibration import CalibrationReport
from trading_platform.model.contracts import Prediction


class UncertaintyAssessmentError(ValueError):
    """Raised when uncertainty evidence is missing, stale, or internally inconsistent."""


CALIBRATION_RISK_CAPS: Mapping[str, Decimal] = MappingProxyType({
    "CALIBRATED": Decimal("1"),
    "ACCEPTABLE": Decimal("0.50"),
    "POOR": Decimal("0.25"),
    "UNKNOWN": Decimal("0.25"),
})


def _epoch_ns(value: datetime) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise UncertaintyAssessmentError("UNCERTAINTY_PREDICTION_TIMEZONE_REQUIRED")
    utc_value = value.astimezone(timezone.utc)
    delta = utc_value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ((delta.days * 86400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1_000


def _decimal(value: Decimal | int | float | str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UncertaintyAssessmentError("INVALID_UNCERTAINTY_ASSESSMENT_VALUE") from exc
    if not out.is_finite() or not Decimal("0") <= out <= Decimal("1"):
        raise UncertaintyAssessmentError("INVALID_UNCERTAINTY_ASSESSMENT_VALUE")
    return out


@dataclass(frozen=True)
class UncertaintyAssessment:
    assessment_id: str
    source_evidence_id: str
    prediction_id: str
    model_id: str
    model_version: str
    measurement_method: str
    measurement_version: str
    source: str
    uncertainty: Decimal
    calibration_state: str
    calibration_report_fingerprint: str | None
    calibration_source_id: str | None
    calibration_reference_source_id: str | None
    calibration_sample_size: int
    calibration_reference_sample_size: int
    observed_at_ns: int
    valid_until_ns: int

    @classmethod
    def from_prediction(
        cls,
        prediction: Prediction,
        *,
        artifact_hash: str | None = None,
        calibration_report: CalibrationReport | None = None,
    ) -> "UncertaintyAssessment":
        if not isinstance(prediction, Prediction):
            raise UncertaintyAssessmentError("SIGNED_MODEL_PREDICTION_REQUIRED")
        try:
            prediction.validate()
        except (TypeError, ValueError) as exc:
            raise UncertaintyAssessmentError("INVALID_SIGNED_MODEL_PREDICTION") from exc
        model_hash = artifact_hash or getattr(prediction, "artifact_hash", None)
        if (
            not isinstance(model_hash, str)
            or len(model_hash) != 64
            or any(char not in "0123456789abcdef" for char in model_hash)
        ):
            raise UncertaintyAssessmentError("SIGNED_MODEL_ARTIFACT_HASH_REQUIRED")
        method = getattr(prediction, "uncertainty_method", "SIGNED_MODEL_DECLARED")
        source = getattr(prediction, "uncertainty_source", "SIGNED_MODEL_ARTIFACT_HASH_AND_PREDICTION_ID")
        if method != "SIGNED_MODEL_DECLARED" or source != "SIGNED_MODEL_ARTIFACT_HASH_AND_PREDICTION_ID":
            raise UncertaintyAssessmentError("UNCERTAINTY_MEASUREMENT_SOURCE_UNSUPPORTED")
        if prediction.calibration_state not in CALIBRATION_RISK_CAPS:
            raise UncertaintyAssessmentError("UNKNOWN_CALIBRATION_STATE")
        if calibration_report is not None and not isinstance(calibration_report, CalibrationReport):
            raise UncertaintyAssessmentError("CALIBRATION_REPORT_REQUIRED")
        # The signed manifest's calibration_state is metadata, not calibration evidence.
        # Only a separately computed report can lift the conservative UNKNOWN cap.
        calibration_state = "UNKNOWN"
        calibration_report_fingerprint = None
        calibration_source_id = None
        calibration_reference_source_id = None
        calibration_sample_size = 0
        calibration_reference_sample_size = 0
        if calibration_report is not None:
            try:
                fingerprint = calibration_report.fingerprint
            except (TypeError, ValueError, OverflowError) as exc:
                raise UncertaintyAssessmentError("INVALID_CALIBRATION_REPORT") from exc
            if (
                not calibration_report.is_valid()
                or len(fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in fingerprint)
            ):
                raise UncertaintyAssessmentError("INVALID_CALIBRATION_REPORT")
            calibration_state = calibration_report.state
            calibration_report_fingerprint = fingerprint
            calibration_source_id = calibration_report.source_id
            calibration_reference_source_id = calibration_report.reference_source_id
            calibration_sample_size = calibration_report.sample_size
            calibration_reference_sample_size = calibration_report.reference_sample_size
        provisional = cls(
            assessment_id="",
            source_evidence_id=model_hash,
            prediction_id=prediction.prediction_id,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            measurement_method=method,
            measurement_version="1",
            source=source,
            uncertainty=_decimal(prediction.uncertainty),
            calibration_state=calibration_state,
            calibration_report_fingerprint=calibration_report_fingerprint,
            calibration_source_id=calibration_source_id,
            calibration_reference_source_id=calibration_reference_source_id,
            calibration_sample_size=calibration_sample_size,
            calibration_reference_sample_size=calibration_reference_sample_size,
            observed_at_ns=_epoch_ns(prediction.timestamp),
            valid_until_ns=_epoch_ns(prediction.expires_at),
        )
        identity_json = json.dumps(
            provisional._identity_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assessment_id = f"UA-{sha256(identity_json).hexdigest()[:24]}"
        return cls(**{**provisional.__dict__, "assessment_id": assessment_id})

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "source_evidence_id": self.source_evidence_id,
            "prediction_id": self.prediction_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "measurement_method": self.measurement_method,
            "measurement_version": self.measurement_version,
            "source": self.source,
            "uncertainty": str(self.uncertainty),
            "calibration_state": self.calibration_state,
            "calibration_report_fingerprint": self.calibration_report_fingerprint,
            "calibration_source_id": self.calibration_source_id,
            "calibration_reference_source_id": self.calibration_reference_source_id,
            "calibration_sample_size": self.calibration_sample_size,
            "calibration_reference_sample_size": self.calibration_reference_sample_size,
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
        }

    def payload(self) -> dict[str, Any]:
        return {"assessment_id": self.assessment_id, **self._identity_payload()}

    @property
    def source_fingerprint(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def calibration_risk_cap(self) -> Decimal:
        try:
            return CALIBRATION_RISK_CAPS[self.calibration_state]
        except KeyError as exc:
            raise UncertaintyAssessmentError("UNKNOWN_CALIBRATION_STATE") from exc

    def source_fresh_at(self, now_ns: int) -> bool:
        return self.is_valid() and isinstance(now_ns, int) and not isinstance(now_ns, bool) and self.observed_at_ns <= now_ns < self.valid_until_ns

    def is_valid(self) -> bool:
        try:
            if (
                not self.assessment_id
                or len(self.source_evidence_id) != 64
                or any(char not in "0123456789abcdef" for char in self.source_evidence_id)
                or not self.prediction_id or not self.model_id or not self.model_version
                or self.measurement_method != "SIGNED_MODEL_DECLARED"
                or self.measurement_version != "1"
                or self.source != "SIGNED_MODEL_ARTIFACT_HASH_AND_PREDICTION_ID"
                or self.calibration_state not in CALIBRATION_RISK_CAPS
                or (
                    self.calibration_report_fingerprint is None
                    and (
                        self.calibration_state != "UNKNOWN"
                        or self.calibration_source_id is not None
                        or self.calibration_reference_source_id is not None
                        or self.calibration_sample_size != 0
                        or self.calibration_reference_sample_size != 0
                    )
                )
                or (
                    self.calibration_report_fingerprint is not None
                    and (
                        not isinstance(self.calibration_report_fingerprint, str)
                        or len(self.calibration_report_fingerprint) != 64
                        or any(char not in "0123456789abcdef" for char in self.calibration_report_fingerprint)
                    )
                )
                or self.calibration_sample_size < 0
                or self.calibration_reference_sample_size < 0
                or (
                    self.calibration_state != "UNKNOWN"
                    and (
                        self.calibration_report_fingerprint is None
                        or not self.calibration_source_id
                        or not self.calibration_reference_source_id
                        or self.calibration_source_id == self.calibration_reference_source_id
                        or self.calibration_sample_size < 2
                        or self.calibration_reference_sample_size < 2
                    )
                )
                or not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool)
                or not isinstance(self.valid_until_ns, int) or isinstance(self.valid_until_ns, bool)
                or self.observed_at_ns < 0 or self.valid_until_ns <= self.observed_at_ns
                or _decimal(self.uncertainty) != self.uncertainty
            ):
                return False
            identity_json = json.dumps(
                self._identity_payload(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            expected_id = "UA-" + sha256(identity_json).hexdigest()[:24]
            return self.assessment_id == expected_id
        except (TypeError, ValueError, UncertaintyAssessmentError):
            return False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "UncertaintyAssessment":
        try:
            assessment = cls(
                assessment_id=str(payload["assessment_id"]),
                source_evidence_id=str(payload["source_evidence_id"]),
                prediction_id=str(payload["prediction_id"]),
                model_id=str(payload["model_id"]),
                model_version=str(payload["model_version"]),
                measurement_method=str(payload["measurement_method"]),
                measurement_version=str(payload["measurement_version"]),
                source=str(payload["source"]),
                uncertainty=Decimal(str(payload["uncertainty"])),
                calibration_state=str(payload["calibration_state"]),
                calibration_report_fingerprint=(
                    None if payload.get("calibration_report_fingerprint") is None
                    else str(payload["calibration_report_fingerprint"])
                ),
                calibration_source_id=(None if payload.get("calibration_source_id") is None else str(payload["calibration_source_id"])),
                calibration_reference_source_id=(
                    None if payload.get("calibration_reference_source_id") is None
                    else str(payload["calibration_reference_source_id"])
                ),
                calibration_sample_size=int(payload.get("calibration_sample_size", 0)),
                calibration_reference_sample_size=int(payload.get("calibration_reference_sample_size", 0)),
                observed_at_ns=int(payload["observed_at_ns"]),
                valid_until_ns=int(payload["valid_until_ns"]),
            )
            supplied = dict(payload)
            source_fingerprint = supplied.pop("source_fingerprint", None)
            if (
                not assessment.is_valid()
                or supplied != assessment.payload()
                or (source_fingerprint is not None and source_fingerprint != assessment.source_fingerprint)
            ):
                raise ValueError("INVALID_UNCERTAINTY_ASSESSMENT")
            return assessment
        except Exception as exc:
            raise UncertaintyAssessmentError("INVALID_UNCERTAINTY_ASSESSMENT_PAYLOAD") from exc

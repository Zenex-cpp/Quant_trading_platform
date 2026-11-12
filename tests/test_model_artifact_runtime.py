from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from trading_platform.model.artifact_runtime import (
    MAX_SIGNED_MODEL_BYTES,
    ModelArtifactLoadError,
    SignedLinearModelV1,
    load_signed_linear_model_v1,
)
from trading_platform.model.contracts import ModelArtifactContract, SchemaContract
from trading_platform.v348 import UncertaintyAssessment
from trading_platform.v373.backtest_engine import BacktestStageFunctions, MarketEvent
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityInvalid
from trading_platform.v375.decision_parity import (
    LiveDecisionEngine,
    capture_backtest_decision_trace,
    compare_decision_traces,
)
from trading_platform.v373.backtest_engine import DeterminismClass, ExecutionModelConfig, SimulationMode
from tests._m14_helpers import authorize_runtime_executor


FEATURES = ("close", "volume")
OUTPUTS = (
    "prediction_id", "model_id", "model_version", "timestamp", "feature_version",
    "target_version", "prediction", "probability", "expected_return", "expected_risk",
    "uncertainty", "calibration_state", "valid_from", "expires_at",
)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _payload(**updates):
    payload = {
        "artifact_type": "TRADING_PLATFORM_LINEAR_LOGIT_V1",
        "model_id": "MODEL-ARTIFACT-1",
        "model_version": "MODEL-V1",
        "model_input_schema": {
            "schema_id": "ohlcv-features",
            "version": "FEATURES-V1",
            "fields": list(FEATURES),
        },
        "model_output_schema": {
            "schema_id": "prediction",
            "version": "PREDICTION-V1",
            "fields": list(OUTPUTS),
        },
        "feature_version": "FEATURES-V1",
        "target_version": "TARGET-V1",
        "runtime_compatibility": "CODE-1",
        "dependency_compatibility": "DEPS-1",
        "configuration_compatibility": "CONFIG-1",
        "coefficients": {"close": 0.01, "volume": 0.1},
        "intercept": 0.0,
        "uncertainty": 0.05,
        "calibration_state": "CALIBRATED",
        "prediction_ttl_seconds": 60,
    }
    payload.update(updates)
    return payload


def _signed_artifact(payload=None, *, raw=None):
    if raw is None:
        raw = json.dumps(payload if payload is not None else _payload(), sort_keys=True, separators=(",", ":")).encode()
    elif isinstance(raw, str):
        raw = raw.encode()
    private_key = Ed25519PrivateKey.generate()
    signature = private_key.sign(raw)
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    contract = ModelArtifactContract(
        model_id="MODEL-ARTIFACT-1",
        model_version="MODEL-V1",
        artifact_hash=sha256(raw).hexdigest(),
        model_input_schema=SchemaContract("ohlcv-features", "FEATURES-V1", FEATURES),
        model_output_schema=SchemaContract("prediction", "PREDICTION-V1", OUTPUTS),
        feature_version="FEATURES-V1",
        runtime_compatibility="CODE-1",
        dependency_compatibility="DEPS-1",
        configuration_compatibility="CONFIG-1",
    )
    return raw, signature, public_key, contract


def _load(payload=None, *, raw=None, **overrides) -> SignedLinearModelV1:
    artifact, signature, public_key, contract = _signed_artifact(payload, raw=raw)
    arguments = {
        "signature": signature,
        "trusted_public_key": public_key,
        "contract": contract,
        "target_version": "TARGET-V1",
        "actual_feature_version": "FEATURES-V1",
        "actual_runtime_compatibility": "CODE-1",
        "actual_dependency_compatibility": "DEPS-1",
        "actual_configuration_compatibility": "CONFIG-1",
    }
    arguments.update(overrides)
    return load_signed_linear_model_v1(artifact, **arguments)


def test_signed_linear_artifact_loads_and_predicts_deterministically():
    model = _load()
    features = {"close": 100, "volume": 10}

    first = model.predict(features, timestamp=NOW)
    second = model.predict(features, timestamp=NOW)

    assert first == second
    assert first.model_id == "MODEL-ARTIFACT-1"
    assert first.probability == pytest.approx(0.8807970779778823)
    assert first.prediction_id
    assert first.valid_from == NOW
    assert (first.expires_at - first.valid_from).total_seconds() == 60
    assert model.artifact_hash == model.contract.artifact_hash


def test_signature_and_hash_are_checked_before_model_data_is_loaded():
    raw, signature, public_key, contract = _signed_artifact()
    with pytest.raises(ModelArtifactLoadError, match="MODEL_ARTIFACT_SIGNATURE_INVALID"):
        load_signed_linear_model_v1(
            raw,
            signature=b"0" * 64,
            trusted_public_key=public_key,
            contract=contract,
            target_version="TARGET-V1",
            actual_feature_version="FEATURES-V1",
            actual_runtime_compatibility="CODE-1",
            actual_dependency_compatibility="DEPS-1",
            actual_configuration_compatibility="CONFIG-1",
        )

    with pytest.raises(ModelArtifactLoadError, match="ARTIFACT_INTEGRITY_FAILURE"):
        load_signed_linear_model_v1(
            raw,
            signature=signature,
            trusted_public_key=public_key,
            contract=replace(contract, artifact_hash="0" * 64),
            target_version="TARGET-V1",
            actual_feature_version="FEATURES-V1",
            actual_runtime_compatibility="CODE-1",
            actual_dependency_compatibility="DEPS-1",
            actual_configuration_compatibility="CONFIG-1",
        )


@pytest.mark.parametrize(
    ("actual_field", "actual_value", "message"),
    [
        ("actual_feature_version", "FEATURES-V2", "FEATURE_VERSION_INCOMPATIBLE"),
        ("actual_runtime_compatibility", "CODE-2", "RUNTIME_INCOMPATIBLE"),
        ("actual_dependency_compatibility", "DEPS-2", "DEPENDENCY_INCOMPATIBLE"),
        ("actual_configuration_compatibility", "CONFIG-2", "CONFIGURATION_INCOMPATIBLE"),
    ],
)
def test_contract_compatibility_mismatch_blocks_model_load(actual_field, actual_value, message):
    with pytest.raises(ModelArtifactLoadError, match=message):
        _load(**{actual_field: actual_value})


def test_untrusted_key_malformed_json_and_oversized_artifact_fail_closed():
    raw, signature, public_key, contract = _signed_artifact()
    wrong_key = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    with pytest.raises(ModelArtifactLoadError, match="MODEL_ARTIFACT_SIGNATURE_INVALID"):
        load_signed_linear_model_v1(
            raw,
            signature=signature,
            trusted_public_key=wrong_key,
            contract=contract,
            target_version="TARGET-V1",
            actual_feature_version="FEATURES-V1",
            actual_runtime_compatibility="CODE-1",
            actual_dependency_compatibility="DEPS-1",
            actual_configuration_compatibility="CONFIG-1",
        )

    duplicate_json = b'{"artifact_type":"TRADING_PLATFORM_LINEAR_LOGIT_V1","artifact_type":"OTHER"}'
    duplicate_key, duplicate_signature, duplicate_public_key, duplicate_contract = _signed_artifact(raw=duplicate_json)
    with pytest.raises(ModelArtifactLoadError, match="MODEL_ARTIFACT_DUPLICATE_JSON_KEY"):
        load_signed_linear_model_v1(
            duplicate_key,
            signature=duplicate_signature,
            trusted_public_key=duplicate_public_key,
            contract=duplicate_contract,
            target_version="TARGET-V1",
            actual_feature_version="FEATURES-V1",
            actual_runtime_compatibility="CODE-1",
            actual_dependency_compatibility="DEPS-1",
            actual_configuration_compatibility="CONFIG-1",
        )

    with pytest.raises(ModelArtifactLoadError, match="MODEL_ARTIFACT_SIZE_LIMIT_EXCEEDED"):
        load_signed_linear_model_v1(
            b"x" * (MAX_SIGNED_MODEL_BYTES + 1),
            signature=b"0" * 64,
            trusted_public_key=public_key,
            contract=contract,
            target_version="TARGET-V1",
            actual_feature_version="FEATURES-V1",
            actual_runtime_compatibility="CODE-1",
            actual_dependency_compatibility="DEPS-1",
            actual_configuration_compatibility="CONFIG-1",
        )


@pytest.mark.parametrize(
    ("payload_updates", "message"),
    [
        ({"target_version": "TARGET-V2"}, "MODEL_ARTIFACT_TARGET_VERSION_MISMATCH"),
        ({"coefficients": {"close": 0.5}}, "MODEL_ARTIFACT_COEFFICIENT_SCHEMA_MISMATCH"),
        ({"coefficients": {"close": float("nan"), "volume": 0.1}}, "MODEL_ARTIFACT_NONFINITE_JSON_NUMBER"),
        ({"prediction_ttl_seconds": 0}, "MODEL_ARTIFACT_PREDICTION_TTL_INVALID"),
        ({"prediction_ttl_seconds": 700000}, "MODEL_ARTIFACT_PREDICTION_TTL_INVALID"),
        ({"uncertainty": 1.1}, "MODEL_ARTIFACT_UNCERTAINTY_INVALID"),
        ({"calibration_state": "UNREVIEWED"}, "MODEL_ARTIFACT_CALIBRATION_STATE_INVALID"),
    ],
)
def test_model_manifest_constraints_fail_closed(payload_updates, message):
    with pytest.raises(ModelArtifactLoadError, match=message):
        _load(_payload(**payload_updates))


def test_signed_prediction_carries_recomputable_uncertainty_source():
    prediction = _load().predict({"close": 100, "volume": 10}, timestamp=NOW)
    assessment = UncertaintyAssessment.from_prediction(prediction)
    assert prediction.artifact_hash == assessment.source_evidence_id
    assert prediction.prediction_id == assessment.prediction_id
    assert assessment.is_valid()
    assert prediction.calibration_state == "CALIBRATED"  # Manifest metadata is not empirical evidence.
    assert assessment.calibration_state == "UNKNOWN"
    assert assessment.calibration_report_fingerprint is None


@pytest.mark.parametrize(
    ("features", "timestamp", "message"),
    [
        ({"close": 100}, NOW, "MODEL_FEATURE_SCHEMA_MISMATCH"),
        ({"close": float("nan"), "volume": 10}, NOW, "MODEL_ARTIFACT_FEATURE_FINITE_REQUIRED"),
        ({"close": 100, "volume": 10}, datetime(2026, 1, 1), "MODEL_PREDICTION_TIMEZONE_REQUIRED"),
    ],
)
def test_prediction_validates_features_and_clock(features, timestamp, message):
    with pytest.raises(ModelArtifactLoadError, match=message):
        _load().predict(features, timestamp=timestamp)


def test_signed_model_callable_integrates_with_guarded_live_decision_trace():
    model = _load()
    events = tuple(
        MarketEvent(
            event_offset=offset,
            event_time=NOW.replace(minute=offset),
            symbol="BTCUSDT",
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )
        for offset in (0, 1)
    )
    stages = BacktestStageFunctions(
        feature_fn=lambda event: {"close": event.close, "volume": event.volume},
        regime_fn=lambda event, feature: "TREND",
        prediction_fn=model,
        signal_fn=lambda event, prediction: prediction.probability > 0.5,
        opportunity_fn=lambda event, signal, regime: {"score": 1 if signal else 0, "regime": regime},
        portfolio_fn=lambda event, opportunity, quantity: {"qty": 0, "position_before": quantity},
        risk_fn=lambda event, decision, quantity: {"allowed": False, "qty": 0, "position_before": quantity},
        intent_fn=lambda event, risk: None,
    )
    execution_model = ExecutionModelConfig(
        version="PARITY-BASE",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )
    backtest_trace, _ = capture_backtest_decision_trace(stages, execution_model, "BTCUSDT", events)
    live_trace = LiveDecisionEngine(
        stages,
        compatibility_executor=authorize_runtime_executor(
            NOW,
            artifact_id=model.contract.model_id,
            artifact_hashes=(model.artifact_hash,),
        ),
        now_provider=lambda: NOW,
    ).run(events, backtest_trace.position_quantities)

    comparison = compare_decision_traces(backtest_trace, live_trace.trace)

    assert comparison.passed
    assert all(intent is None for intent in live_trace.intents)


def test_m14_grant_must_bind_the_loaded_model_id_and_hash():
    model = _load()
    event = MarketEvent(
        event_offset=0,
        event_time=NOW,
        symbol="BTCUSDT",
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("10"),
    )
    stages = BacktestStageFunctions(
        feature_fn=lambda current: {"close": current.close, "volume": current.volume},
        regime_fn=lambda current, feature: "TREND",
        prediction_fn=model,
        signal_fn=lambda current, prediction: prediction.probability > 0.5,
        opportunity_fn=lambda current, signal, regime: {"score": 1 if signal else 0, "regime": regime},
        portfolio_fn=lambda current, opportunity, quantity: {"qty": 0, "position_before": quantity},
        risk_fn=lambda current, decision, quantity: {"allowed": False, "qty": 0, "position_before": quantity},
        intent_fn=lambda current, risk: None,
    )
    engine = LiveDecisionEngine(
        stages,
        compatibility_executor=authorize_runtime_executor(
            NOW,
            artifact_id=model.contract.model_id,
            artifact_hashes=("sha256:not-the-loaded-model",),
        ),
        now_provider=lambda: NOW,
    )

    with pytest.raises(CompatibilityAuthorityInvalid, match="ARTIFACT_EXECUTABLE_BINDING_MISMATCH"):
        engine.run((event,), (Decimal("0"),))

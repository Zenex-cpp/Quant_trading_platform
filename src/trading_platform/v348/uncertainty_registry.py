from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UncertaintyMethodSpec:
    method: str
    version: str
    source: str
    definition: str
    minimum_uncertainty: str
    maximum_uncertainty: str
    threshold: str
    action: str
    monitoring: str
    production_eligible: bool = True


PRODUCTION_UNCERTAINTY_METHODS: tuple[UncertaintyMethodSpec, ...] = (
    UncertaintyMethodSpec(
        method="CONSERVATIVE_LINEAR",
        version="1",
        source="SOURCE_BOUND_MODEL_UNCERTAINTY_ASSESSMENT",
        definition="risk_factor=max(floor, 1-min(1, uncertainty/max_uncertainty))",
        minimum_uncertainty="0",
        maximum_uncertainty="1",
        threshold="uncertainty>=max_uncertainty => risk_factor=floor",
        action="HIGHER_UNCERTAINTY_REDUCES_OR_PRESERVES_RISK",
        monitoring="MONOTONICITY_ABLATION_AND_CALIBRATION_DRIFT_REQUIRED",
        production_eligible=True,
    ),
)


UNCERTAINTY_MEASURE_SPECS: tuple[UncertaintyMethodSpec, ...] = (
    UncertaintyMethodSpec(
        method="SIGNED_MODEL_DECLARED",
        version="1",
        source="SIGNED_MODEL_ARTIFACT_HASH_AND_PREDICTION_ID",
        definition="uncertainty value declared by the signed model artifact manifest",
        minimum_uncertainty="0",
        maximum_uncertainty="1",
        threshold="state UNKNOWN or POOR => risk_factor<=0.25; ACCEPTABLE=><=0.50",
        action="CAP_RISK_AND_REQUIRE_FRESH_SOURCE_BOUND_PREDICTION",
        monitoring="CALIBRATION_BRIER_ECE_RELIABILITY_AND_REFERENCE_WINDOW_DRIFT",
        production_eligible=False,
    ),
    UncertaintyMethodSpec(
        method="BERNOULLI_ENTROPY_NORMALIZED",
        version="1",
        source="SIGNED_PREDICTION_PROBABILITY",
        definition="-(p*ln(p)+(1-p)*ln(1-p))/ln(2), with endpoint values defined as zero",
        minimum_uncertainty="0",
        maximum_uncertainty="1",
        threshold="uncertainty>=0.80 => apply conservative risk mapping",
        action="HIGHER_ENTROPY_REDUCES_OR_PRESERVES_RISK",
        monitoring="OUT_OF_SAMPLE_CALIBRATION_AND_MONOTONICITY_ABLATION_REQUIRED",
        production_eligible=False,
    ),
    UncertaintyMethodSpec(
        method="ENSEMBLE_DISPERSION_VARIANCE",
        version="1",
        source="SIGNED_ENSEMBLE_MEMBER_PREDICTIONS_AND_ARTIFACT_HASHES",
        definition="population variance of member probabilities in [0,1]",
        minimum_uncertainty="0",
        maximum_uncertainty="0.25",
        threshold="uncertainty>=0.0625 => apply conservative risk mapping",
        action="HIGHER_DISPERSION_REDUCES_OR_PRESERVES_RISK",
        monitoring="INDEPENDENT_MEMBER_PROVENANCE_AND_OUT_OF_SAMPLE_ABLATION_REQUIRED",
        production_eligible=False,
    ),
)


def get_production_uncertainty_method(method: str, version: str) -> UncertaintyMethodSpec:
    for spec in PRODUCTION_UNCERTAINTY_METHODS:
        if spec.method == method and spec.version == version:
            return spec
    raise ValueError("UNCERTAINTY_METHOD_NOT_REGISTERED")

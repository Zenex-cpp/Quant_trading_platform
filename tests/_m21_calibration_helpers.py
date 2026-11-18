"""Explicit synthetic calibration evidence for runtime authority tests."""
from trading_platform.model.calibration import calibration_report


def synthetic_calibration_report(source_id: str = "TEST-CURRENT", reference_source_id: str = "TEST-REFERENCE"):
    probabilities = [0.01] * 15 + [0.99] * 15
    outcomes = [0] * 15 + [1] * 15
    return calibration_report(
        probabilities,
        outcomes,
        source_id=source_id,
        reference_probabilities=probabilities,
        reference_outcomes=outcomes,
        reference_source_id=reference_source_id,
    )

"""Adversarial candidate-falsification checks."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AdversarialFinding:
    check_id: str
    category: str
    severity: str
    finding: str
    evidence: str
    remediation: str


REQUIRED_CHECKS=("LEAKAGE","OVERFIT","FRAGILE_PARAMETERS","REGIME_DEPENDENCE","COST_DEPENDENCE","CAPACITY","LUCKY_SEQUENCE","SUSPICIOUS_FEATURE_DEPENDENCE","TEMPORAL_INSTABILITY")


def require_all_checks(findings: list[AdversarialFinding]) -> None:
    covered={x.category for x in findings}
    missing=[c for c in REQUIRED_CHECKS if c not in covered]
    if missing: raise ValueError(f"ADVERSARIAL_CHECKS_MISSING:{missing}")

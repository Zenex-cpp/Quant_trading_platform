"""Versioned decision-TTL policy for §20 and downstream causality."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class TTLPolicyError(ValueError):
    """A TTL policy or window violates the normative contract."""


@dataclass(frozen=True)
class TTLPolicy:
    decision_class: str
    artifact_type: str
    required: bool
    expiry_precedence: str
    downstream_rule: str
    on_expiry: str
    implementation_reference: str


class TTLPolicyRegistry:
    REQUIRED_CLASSES = {
        "Prediction": "PREDICTION",
        "Signal": "SIGNAL",
        "Opportunity Score": "OPPORTUNITY",
        "Portfolio Allocation Decision": "PORTFOLIO_DECISION",
        "Risk Decision": "RISK_DECISION",
        "Order Intent": "ORDER_INTENT",
    }

    def __init__(self, policies: tuple[TTLPolicy, ...]):
        if not policies:
            raise TTLPolicyError("TTL_POLICY_EMPTY")
        if len({item.decision_class for item in policies}) != len(policies):
            raise TTLPolicyError("TTL_POLICY_DUPLICATE")
        if {item.decision_class: item.artifact_type for item in policies} != self.REQUIRED_CLASSES:
            raise TTLPolicyError("TTL_POLICY_COVERAGE_INVALID")
        if len({item.artifact_type for item in policies}) != len(policies):
            raise TTLPolicyError("TTL_POLICY_ARTIFACT_DUPLICATE")
        if any(not item.required for item in policies):
            raise TTLPolicyError("TTL_POLICY_REQUIRED_FLAG_FALSE")
        if any(
            item.expiry_precedence != "UPSTREAM_EXPIRES_FIRST"
            or item.downstream_rule != "REQUIRE_ALL_UPSTREAM_VALID"
            or item.on_expiry != "BLOCK_NEW_RISK"
            or not item.implementation_reference
            for item in policies
        ):
            raise TTLPolicyError("TTL_POLICY_FAIL_OPEN")
        self._policies = tuple(policies)
        self._by_class = {item.decision_class: item for item in policies}

    @classmethod
    def from_csv(cls, path: Path) -> "TTLPolicyRegistry":
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
        except OSError as exc:
            raise TTLPolicyError("TTL_POLICY_UNREADABLE") from exc
        required = {
            "decision_class", "artifact_type", "required", "expiry_precedence",
            "downstream_rule", "on_expiry", "implementation_reference",
        }
        if not rows or set(rows[0]) != required:
            raise TTLPolicyError("TTL_POLICY_SCHEMA_INVALID")
        policies: list[TTLPolicy] = []
        for row in rows:
            if row.get("required") != "TRUE":
                raise TTLPolicyError("TTL_POLICY_REQUIRED_FLAG_INVALID")
            policies.append(
                TTLPolicy(
                    decision_class=row["decision_class"],
                    artifact_type=row["artifact_type"],
                    required=True,
                    expiry_precedence=row["expiry_precedence"],
                    downstream_rule=row["downstream_rule"],
                    on_expiry=row["on_expiry"],
                    implementation_reference=row["implementation_reference"],
                )
            )
        return cls(tuple(policies))

    @property
    def policies(self) -> tuple[TTLPolicy, ...]:
        return self._policies

    def policy_for(self, decision_class: str) -> TTLPolicy:
        try:
            return self._by_class[decision_class]
        except KeyError as exc:
            raise TTLPolicyError("TTL_DECISION_CLASS_NOT_REGISTERED") from exc

    def assert_window(self, decision_class: str, valid_from: datetime, expires_at: datetime, now: datetime) -> None:
        self.policy_for(decision_class)
        if any(value.utcoffset() is None for value in (valid_from, expires_at, now)):
            raise TTLPolicyError("TTL_TIMEZONE_REQUIRED")
        if valid_from >= expires_at:
            raise TTLPolicyError("TTL_WINDOW_INVALID")
        if not valid_from <= now < expires_at:
            raise TTLPolicyError("TTL_EXPIRED_OR_NOT_YET_VALID")

    @staticmethod
    def assert_downstream_not_longer(*, downstream_expires_at: datetime, upstream_expires_at: datetime) -> None:
        if downstream_expires_at.utcoffset() is None or upstream_expires_at.utcoffset() is None:
            raise TTLPolicyError("TTL_TIMEZONE_REQUIRED")
        if downstream_expires_at > upstream_expires_at:
            raise TTLPolicyError("TTL_DOWNSTREAM_OUTLIVES_UPSTREAM")

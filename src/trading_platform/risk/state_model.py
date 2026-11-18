"""Machine-readable risk-state model used by the §13/§179 contract."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trading_platform.v318.durable_decision import RiskSystemState


class RiskStateModelError(ValueError):
    """The risk-state catalog is malformed or unsafe."""


@dataclass(frozen=True)
class RiskStateDefinition:
    state: RiskSystemState
    severity: int
    risk_factor: Decimal
    new_risk_action: str
    existing_position_action: str
    recovery_requirement: str
    source_reference: str


class RiskStateModel:
    """Validated catalog of every risk state and its conservative cap."""

    def __init__(self, definitions: tuple[RiskStateDefinition, ...]):
        if not definitions:
            raise RiskStateModelError("RISK_STATE_CATALOG_EMPTY")
        if len({item.state for item in definitions}) != len(definitions):
            raise RiskStateModelError("RISK_STATE_DUPLICATE")
        ordered = tuple(sorted(definitions, key=lambda item: item.severity))
        if tuple(item.state for item in ordered) != tuple(RiskSystemState):
            raise RiskStateModelError("RISK_STATE_CATALOG_INCOMPLETE")
        if [item.severity for item in ordered] != list(range(len(ordered))):
            raise RiskStateModelError("RISK_STATE_SEVERITY_NOT_CONTIGUOUS")
        if any(not item.risk_factor.is_finite() or item.risk_factor < 0 or item.risk_factor > 1 for item in ordered):
            raise RiskStateModelError("RISK_STATE_FACTOR_OUT_OF_RANGE")
        if any(left.risk_factor < right.risk_factor for left, right in zip(ordered, ordered[1:])):
            raise RiskStateModelError("RISK_STATE_FACTOR_NOT_CONSERVATIVE")
        if any(
            not item.new_risk_action
            or not item.existing_position_action
            or not item.recovery_requirement
            or not item.source_reference
            for item in ordered
        ):
            raise RiskStateModelError("RISK_STATE_POLICY_FIELDS_REQUIRED")
        if any(
            (item.risk_factor == 0 and not item.new_risk_action.startswith("BLOCK"))
            or (item.risk_factor > 0 and not item.new_risk_action.startswith("ALLOW"))
            for item in ordered
        ):
            raise RiskStateModelError("RISK_STATE_ACTION_FACTOR_MISMATCH")
        self._definitions = ordered
        self._by_state = {item.state: item for item in ordered}

    @classmethod
    def from_csv(cls, path: Path) -> "RiskStateModel":
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
        except OSError as exc:
            raise RiskStateModelError("RISK_STATE_CATALOG_UNREADABLE") from exc
        required = {
            "state_id", "severity", "risk_factor", "new_risk_action",
            "existing_position_action", "recovery_requirement", "source_reference",
        }
        if not rows or set(rows[0]) != required:
            raise RiskStateModelError("RISK_STATE_CATALOG_SCHEMA_INVALID")
        definitions: list[RiskStateDefinition] = []
        try:
            for row in rows:
                definitions.append(
                    RiskStateDefinition(
                        state=RiskSystemState(row["state_id"]),
                        severity=int(row["severity"]),
                        risk_factor=Decimal(row["risk_factor"]),
                        new_risk_action=row["new_risk_action"],
                        existing_position_action=row["existing_position_action"],
                        recovery_requirement=row["recovery_requirement"],
                        source_reference=row["source_reference"],
                    )
                )
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise RiskStateModelError("RISK_STATE_CATALOG_ROW_INVALID") from exc
        return cls(tuple(definitions))

    @property
    def definitions(self) -> tuple[RiskStateDefinition, ...]:
        return self._definitions

    def definition(self, state: RiskSystemState | str) -> RiskStateDefinition:
        try:
            normalized = state if isinstance(state, RiskSystemState) else RiskSystemState(str(state))
            return self._by_state[normalized]
        except (ValueError, KeyError) as exc:
            raise RiskStateModelError("RISK_STATE_NOT_REGISTERED") from exc

    def maximum_new_risk(self, state: RiskSystemState | str, baseline_limit: Decimal) -> Decimal:
        definition = self.definition(state)
        try:
            baseline = Decimal(str(baseline_limit))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise RiskStateModelError("RISK_STATE_BASELINE_LIMIT_INVALID") from exc
        if not baseline.is_finite() or baseline < 0:
            raise RiskStateModelError("RISK_STATE_BASELINE_LIMIT_INVALID")
        return baseline * definition.risk_factor

    def assert_new_risk_allowed(
        self,
        state: RiskSystemState | str,
        requested_amount: Decimal,
        baseline_limit: Decimal,
    ) -> None:
        try:
            requested = Decimal(str(requested_amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise RiskStateModelError("RISK_STATE_AMOUNT_INVALID") from exc
        if not requested.is_finite() or requested < 0:
            raise RiskStateModelError("RISK_STATE_AMOUNT_INVALID")
        definition = self.definition(state)
        if definition.risk_factor == 0 and requested > 0:
            raise RiskStateModelError("RISK_STATE_NEW_RISK_BLOCKED")
        maximum = self.maximum_new_risk(state, baseline_limit)
        if requested > maximum:
            raise RiskStateModelError("RISK_STATE_NEW_RISK_EXCEEDS_STATE_CAP")

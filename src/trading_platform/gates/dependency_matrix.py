"""Exhaustive gate dependency matrix for promotion and activation."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class GateDependencyError(ValueError):
    """The gate dependency graph is malformed or a prerequisite is absent."""


@dataclass(frozen=True)
class GateDependency:
    gate_id: str
    stage: str
    depends_on: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    failure_action: str
    implementation_reference: str


class GateDependencyMatrix:
    def __init__(self, gates: tuple[GateDependency, ...]):
        if not gates:
            raise GateDependencyError("GATE_MATRIX_EMPTY")
        if len({item.gate_id for item in gates}) != len(gates):
            raise GateDependencyError("GATE_MATRIX_DUPLICATE")
        by_id = {item.gate_id: item for item in gates}
        if any(not item.required_artifacts or not item.failure_action or not item.implementation_reference for item in gates):
            raise GateDependencyError("GATE_MATRIX_FIELDS_REQUIRED")
        for item in gates:
            if item.gate_id in item.depends_on or any(dep not in by_id for dep in item.depends_on):
                raise GateDependencyError("GATE_MATRIX_UNKNOWN_OR_SELF_DEPENDENCY")
        self._gates = tuple(gates)
        self._by_id = by_id
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(gate_id: str) -> None:
            if gate_id in visiting:
                raise GateDependencyError("GATE_MATRIX_CYCLE")
            if gate_id in visited:
                return
            visiting.add(gate_id)
            for dependency in self._by_id[gate_id].depends_on:
                visit(dependency)
            visiting.remove(gate_id)
            visited.add(gate_id)

        for gate_id in self._by_id:
            visit(gate_id)

    @classmethod
    def from_csv(cls, path: Path) -> "GateDependencyMatrix":
        required = {"gate_id", "stage", "depends_on", "required_artifacts", "failure_action", "implementation_reference"}
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if set(reader.fieldnames or ()) != required:
                    raise GateDependencyError("GATE_MATRIX_SCHEMA_INVALID")
                gates = tuple(
                    GateDependency(
                        gate_id=row["gate_id"],
                        stage=row["stage"],
                        depends_on=tuple(filter(None, row["depends_on"].split("|"))),
                        required_artifacts=tuple(filter(None, row["required_artifacts"].split("|"))),
                        failure_action=row["failure_action"],
                        implementation_reference=row["implementation_reference"],
                    )
                    for row in reader
                )
        except OSError as exc:
            raise GateDependencyError("GATE_MATRIX_UNREADABLE") from exc
        except KeyError as exc:
            raise GateDependencyError("GATE_MATRIX_ROW_INVALID") from exc
        return cls(gates)

    @property
    def gates(self) -> tuple[GateDependency, ...]:
        return self._gates

    def dependencies_for(self, gate_id: str) -> tuple[str, ...]:
        try:
            return self._by_id[gate_id].depends_on
        except KeyError as exc:
            raise GateDependencyError("GATE_NOT_REGISTERED") from exc

    def assert_satisfied(
        self,
        gate_id: str,
        passed_gates: set[str],
        available_artifacts: set[str],
    ) -> None:
        if gate_id not in self._by_id:
            raise GateDependencyError("GATE_NOT_REGISTERED")
        required_gates: set[str] = set()

        def collect(current: str) -> None:
            if current in required_gates:
                return
            required_gates.add(current)
            for dependency in self.dependencies_for(current):
                collect(dependency)

        collect(gate_id)
        missing_gates = required_gates - passed_gates
        if missing_gates:
            raise GateDependencyError("GATE_DEPENDENCY_NOT_SATISFIED:" + ",".join(sorted(missing_gates)))
        required_artifacts = {
            artifact
            for required_gate in required_gates
            for artifact in self._by_id[required_gate].required_artifacts
        }
        missing_artifacts = required_artifacts - available_artifacts
        if missing_artifacts:
            raise GateDependencyError("GATE_ARTIFACT_NOT_SATISFIED:" + ",".join(sorted(missing_artifacts)))

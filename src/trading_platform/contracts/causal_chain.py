"""Canonical §21 causal artifact chain loader and fail-closed validator."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class CausalChainError(ValueError):
    """The causal chain catalog or an artifact instance is invalid."""


@dataclass(frozen=True)
class CausalChainNode:
    sequence: int
    artifact_type: str
    required_upstream: tuple[str, ...]
    required_fields: tuple[str, ...]
    ttl_rule: str
    state_rule: str
    provenance_rule: str


@dataclass(frozen=True)
class CausalArtifact:
    artifact_type: str
    payload: Mapping[str, object]


class CausalChainRegistry:
    """Validated catalog that checks the full available ancestry before use."""

    _VALID_STATES = frozenset({"VALID", "APPROVED", "ACTIVE"})
    _DEPENDENCY_FIELD = "dependency_ids"

    def __init__(self, nodes: tuple[CausalChainNode, ...]):
        if not nodes:
            raise CausalChainError("CAUSAL_CHAIN_EMPTY")
        ordered = tuple(sorted(nodes, key=lambda item: item.sequence))
        if [item.sequence for item in ordered] != list(range(1, len(ordered) + 1)):
            raise CausalChainError("CAUSAL_CHAIN_SEQUENCE_INVALID")
        names = {item.artifact_type for item in ordered}
        if len(names) != len(ordered):
            raise CausalChainError("CAUSAL_CHAIN_DUPLICATE_ARTIFACT")
        seen: set[str] = set()
        for node in ordered:
            if (
                not node.required_fields
                or not node.ttl_rule
                or not node.state_rule
                or not node.provenance_rule
            ):
                raise CausalChainError("CAUSAL_CHAIN_NODE_FIELDS_REQUIRED")
            if node.state_rule != "VALID_OR_APPROVED_OR_ACTIVE":
                raise CausalChainError("CAUSAL_CHAIN_STATE_RULE_UNSUPPORTED")
            if node.provenance_rule != "provenance_id_and_fingerprint_required":
                raise CausalChainError("CAUSAL_CHAIN_PROVENANCE_RULE_UNSUPPORTED")
            if any(dep not in seen for dep in node.required_upstream):
                raise CausalChainError("CAUSAL_CHAIN_FORWARD_DEPENDENCY")
            if len(set(node.required_upstream)) != len(node.required_upstream):
                raise CausalChainError("CAUSAL_CHAIN_DUPLICATE_DEPENDENCY")
            if self._DEPENDENCY_FIELD not in node.required_fields:
                raise CausalChainError("CAUSAL_CHAIN_DEPENDENCY_FIELD_REQUIRED")
            seen.add(node.artifact_type)
        if ordered[0].required_upstream:
            raise CausalChainError("CAUSAL_CHAIN_ROOT_HAS_DEPENDENCY")
        self._nodes = ordered
        self._by_type = {item.artifact_type: item for item in ordered}

    @classmethod
    def from_csv(cls, path: Path) -> "CausalChainRegistry":
        required = {
            "sequence", "artifact_type", "required_upstream", "required_fields",
            "ttl_rule", "state_rule", "provenance_rule",
        }
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if set(reader.fieldnames or ()) != required:
                    raise CausalChainError("CAUSAL_CHAIN_SCHEMA_INVALID")
                nodes = []
                for row in reader:
                    nodes.append(
                        CausalChainNode(
                            sequence=int(row["sequence"]),
                            artifact_type=row["artifact_type"],
                            required_upstream=tuple(filter(None, row["required_upstream"].split("|"))),
                            required_fields=tuple(filter(None, row["required_fields"].split("|"))),
                            ttl_rule=row["ttl_rule"],
                            state_rule=row["state_rule"],
                            provenance_rule=row["provenance_rule"],
                        )
                    )
        except OSError as exc:
            raise CausalChainError("CAUSAL_CHAIN_UNREADABLE") from exc
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CausalChainError):
                raise
            raise CausalChainError("CAUSAL_CHAIN_ROW_INVALID") from exc
        return cls(tuple(nodes))

    @property
    def nodes(self) -> tuple[CausalChainNode, ...]:
        return self._nodes

    def node(self, artifact_type: str) -> CausalChainNode:
        try:
            return self._by_type[artifact_type]
        except KeyError as exc:
            raise CausalChainError("CAUSAL_ARTIFACT_TYPE_NOT_REGISTERED") from exc

    def validate_artifact(
        self,
        artifact_type: str,
        payload: Mapping[str, object],
        available_artifacts: Sequence[CausalArtifact],
        *,
        now_ms: int,
    ) -> None:
        """Validate this artifact and recursively validate each required ancestor.

        `available_artifacts` supplies previously persisted causal records. Every record
        referenced by `dependency_ids` must be present, valid at `now_ms`, and expire no
        earlier than the artifact that depends on it.
        """
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
            raise CausalChainError("CAUSAL_CLOCK_INVALID")
        current = CausalArtifact(artifact_type=artifact_type, payload=payload)
        available_by_id: dict[str, CausalArtifact] = {}
        for artifact in available_artifacts:
            artifact_id = artifact.payload.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                raise CausalChainError("CAUSAL_ARTIFACT_ID_REQUIRED")
            if artifact_id in available_by_id:
                raise CausalChainError("CAUSAL_ARTIFACT_ID_DUPLICATE")
            available_by_id[artifact_id] = artifact

        current_id = current.payload.get("artifact_id")
        if not isinstance(current_id, str) or not current_id.strip():
            raise CausalChainError("CAUSAL_ARTIFACT_ID_REQUIRED")
        if current_id in available_by_id:
            raise CausalChainError("CAUSAL_ARTIFACT_ID_ALREADY_EXISTS")
        available_by_id[current_id] = current

        visiting: set[str] = set()
        validated: set[str] = set()

        def visit(artifact: CausalArtifact) -> None:
            node = self.node(artifact.artifact_type)
            data = artifact.payload
            artifact_id = data.get("artifact_id")
            assert isinstance(artifact_id, str)
            if artifact_id in visiting:
                raise CausalChainError("CAUSAL_DEPENDENCY_CYCLE")
            if artifact_id in validated:
                return

            missing = [
                field for field in node.required_fields
                if field != self._DEPENDENCY_FIELD
                and (field not in data or data[field] is None or (isinstance(data[field], str) and not data[field].strip()))
            ]
            if missing:
                raise CausalChainError("CAUSAL_REQUIRED_FIELDS_MISSING:" + ",".join(missing))

            version = data.get("version")
            provenance_id = data.get("provenance_id")
            fingerprint = data.get("fingerprint")
            state = data.get("state")
            if not all(isinstance(value, str) and value.strip() for value in (version, provenance_id, fingerprint)):
                raise CausalChainError("CAUSAL_PROVENANCE_OR_VERSION_INVALID")
            if not isinstance(state, str) or state not in self._VALID_STATES:
                raise CausalChainError("CAUSAL_ARTIFACT_STATE_INVALID")

            timestamp = self._timestamp(data.get("timestamp_ms"), "timestamp_ms")
            valid_from = self._timestamp(data.get("valid_from_ms"), "valid_from_ms")
            expires_at = self._timestamp(data.get("expires_at_ms"), "expires_at_ms")
            if not valid_from <= timestamp < expires_at:
                raise CausalChainError("CAUSAL_ARTIFACT_WINDOW_INVALID")
            if not valid_from <= now_ms < expires_at or timestamp > now_ms:
                raise CausalChainError("CAUSAL_ARTIFACT_EXPIRED_OR_FUTURE")

            dependency_ids = data.get(self._DEPENDENCY_FIELD)
            if not isinstance(dependency_ids, (list, tuple)) or any(
                not isinstance(value, str) or not value.strip() for value in dependency_ids
            ):
                raise CausalChainError("CAUSAL_DEPENDENCY_IDS_INVALID")
            if len(set(dependency_ids)) != len(dependency_ids):
                raise CausalChainError("CAUSAL_DEPENDENCY_ID_DUPLICATE")
            if len(dependency_ids) != len(node.required_upstream):
                raise CausalChainError("CAUSAL_REQUIRED_UPSTREAM_MISSING:" + artifact.artifact_type)

            dependencies: list[CausalArtifact] = []
            for dependency_id in dependency_ids:
                dependency = available_by_id.get(dependency_id)
                if dependency is None or dependency is artifact:
                    raise CausalChainError("CAUSAL_REQUIRED_UPSTREAM_MISSING:" + artifact.artifact_type)
                dependencies.append(dependency)
            dependency_types = [item.artifact_type for item in dependencies]
            if len(set(dependency_types)) != len(dependency_types) or set(dependency_types) != set(node.required_upstream):
                raise CausalChainError("CAUSAL_REQUIRED_UPSTREAM_MISMATCH:" + artifact.artifact_type)

            visiting.add(artifact_id)
            for dependency in dependencies:
                visit(dependency)
                upstream = dependency.payload
                upstream_expires = self._timestamp(upstream.get("expires_at_ms"), "expires_at_ms")
                upstream_timestamp = self._timestamp(upstream.get("timestamp_ms"), "timestamp_ms")
                if expires_at > upstream_expires:
                    raise CausalChainError("CAUSAL_DOWNSTREAM_OUTLIVES_UPSTREAM")
                if timestamp < upstream_timestamp:
                    raise CausalChainError("CAUSAL_TIMESTAMP_PRECEDES_UPSTREAM")
            visiting.remove(artifact_id)
            validated.add(artifact_id)

        visit(current)

    @staticmethod
    def _timestamp(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CausalChainError("CAUSAL_TIMESTAMP_INVALID:" + field)
        return value

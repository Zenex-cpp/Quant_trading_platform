from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

class Compatibility(str, Enum):
    COMPATIBLE="COMPATIBLE"
    INCOMPATIBLE="INCOMPATIBLE"
    UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class CompatibilityReport:
    runtime_input_schema: Compatibility
    output_schema: Compatibility
    feature_schema: Compatibility
    configuration: Compatibility
    dependencies: Compatibility
    execution: Compatibility
    venue_rules: Compatibility
    def overall(self)->Compatibility:
        vals=(self.runtime_input_schema,self.output_schema,self.feature_schema,self.configuration,self.dependencies,self.execution,self.venue_rules)
        if Compatibility.INCOMPATIBLE in vals: return Compatibility.INCOMPATIBLE
        if Compatibility.UNKNOWN in vals: return Compatibility.UNKNOWN
        return Compatibility.COMPATIBLE

    @property
    def fingerprint(self)->str:
        payload = {
            "runtime_input_schema": self.runtime_input_schema.value,
            "output_schema": self.output_schema.value,
            "feature_schema": self.feature_schema.value,
            "configuration": self.configuration.value,
            "dependencies": self.dependencies.value,
            "execution": self.execution.value,
            "venue_rules": self.venue_rules.value,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def assert_deployable(report: CompatibilityReport)->None:
    if report.overall()!=Compatibility.COMPATIBLE:
        raise ValueError(f"ARTIFACT_COMPATIBILITY_{report.overall().value}")

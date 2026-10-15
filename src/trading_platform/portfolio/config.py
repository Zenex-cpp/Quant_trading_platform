from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping, Any

class Precedence(IntEnum):
    DEFAULT=10
    CONFIG_FILE=20
    ENVIRONMENT=30
    RUNTIME=40
    SAFETY_OVERRIDE=50

@dataclass(frozen=True)
class ConfigValue:
    name: str
    value: Any
    precedence: Precedence
    source: str
    version: str
    immutable: bool=False

def resolve_config(values: list[ConfigValue]) -> ConfigValue:
    if not values:
        raise ValueError("NO_CONFIG_VALUE")
    values=sorted(values, key=lambda x: x.precedence, reverse=True)
    top=values[0]
    conflicting=[v for v in values[1:] if v.precedence==top.precedence and v.value!=top.value]
    if conflicting:
        raise ValueError("CONFIG_CONFLICT")
    return top

from dataclasses import dataclass
from enum import Enum
from typing import Callable

class MethodStatus(str, Enum):
    APPLICABLE="APPLICABLE"
    METHOD_NOT_APPLICABLE="METHOD_NOT_APPLICABLE"

@dataclass(frozen=True)
class MethodSpec:
    method_id: str
    version: str
    assumptions: tuple[str, ...]
    applicability: str
    limitations: tuple[str, ...]
    implementation_reference: str = ""
    required_inputs: tuple[str, ...] = ()
    output_semantics: str = ""

@dataclass(frozen=True)
class MethodCheck:
    method_id: str
    status: MethodStatus
    failed_assumptions: tuple[str, ...]

def check_assumptions(spec: MethodSpec, assumption_results: dict[str,bool]) -> MethodCheck:
    failed=tuple(a for a in spec.assumptions if not assumption_results.get(a,False))
    return MethodCheck(spec.method_id, MethodStatus.METHOD_NOT_APPLICABLE if failed else MethodStatus.APPLICABLE, failed)


class MethodExecutionError(RuntimeError):
    pass


def execute_method(spec: MethodSpec, assumption_results: dict[str, bool], evaluator, *args, **kwargs):
    """Execute only when every declared methodology assumption is satisfied."""
    check = check_assumptions(spec, assumption_results)
    if check.status is MethodStatus.METHOD_NOT_APPLICABLE:
        failed = ",".join(check.failed_assumptions)
        raise MethodExecutionError(f"METHOD_NOT_APPLICABLE:{failed}")
    return evaluator(*args, **kwargs)

import math


def assert_finite(*values: float) -> None:
    for value in values:
        if not math.isfinite(value):
            raise ValueError("NON_FINITE_VALUE")

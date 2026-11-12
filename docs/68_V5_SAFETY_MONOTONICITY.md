# 68 — V5 Safety Monotonicity Matrix

## Scope

This matrix traces the mathematical rules in prompt §§14–17 to the current code and tests. `schemas/v5_safety_monotonicity_matrix.csv` is the machine-readable register. The statuses describe bounded repository components; they do not establish that every production caller uses them.

## Implemented dimensions

The uncertainty, liquidity-stress, drawdown, and model-health authorities derive bounded factors and reject upward overrides. Their ordered-input tests check that worsening conditions cannot increase allowed risk. The M29 risk-state guard compares `remaining_budget`, `available_new_risk`, and `maximum_exposure`; increases on a worsened state require a recovery event with current proof, validation, audit, and per-output caps.

The absolute risk ceiling helper checks effective risk and exposure at its boundary. This does not prove that a platform-owned immutable ceiling is bound at every caller or that model output cannot influence ceiling configuration.

## Remaining gaps

The prompt's execution-risk-to-position-size rule has no dedicated monotone input/factor in the shared `adjusted_risk` function. Portfolio allocation checks a per-instrument `max_concentration`, but there is no monotonicity authority for correlated exposure as concentration worsens. Both remain gaps until their inputs, units, approved mapping, and runtime authority are defined.

FD-08 remains `PARTIAL`. The matrix and tests cover implemented dimensions and expose missing authorities; the execution-risk, correlated-exposure, and global hard-ceiling binding requirements remain incomplete.

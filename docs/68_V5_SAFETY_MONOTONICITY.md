# 68 — V5 Safety Monotonicity Matrix

## Scope

This matrix traces the mathematical rules in prompt §§14–17 to the current code and tests. `schemas/v5_safety_monotonicity_matrix.csv` is the machine-readable register. The statuses describe bounded repository components; they do not establish that every production caller uses them.

## Implemented dimensions

The uncertainty, liquidity-stress, drawdown, and model-health authorities derive bounded factors and reject upward overrides. Their ordered-input tests check that worsening conditions cannot increase allowed risk. The M29 risk-state guard compares `remaining_budget`, `available_new_risk`, and `maximum_exposure`; increases on a worsened state require a recovery event with current proof, validation, audit, and per-output caps.

The execution-risk authority accepts an explicit normalized hazard in `[0, 1]` and maps it linearly to a position-size factor from `1` to `0`. The concentration authority accepts normalized concentration and monotonically reduces the cap for independently measured correlated exposure, reaching zero at the configured maximum. `adjusted_risk` can also bind an execution-risk value and rejects a conflicting factor override.

These are conservative bounded contracts, not estimators. They do not derive execution hazard from spread, slippage, liquidity, or market impact; compute correlation; authenticate the supplied measurements; or prove that every caller invokes the helpers. The absolute risk ceiling helper checks effective risk and exposure at its boundary, but a platform-owned immutable ceiling is not bound at every caller and model output may still influence ceiling configuration.

## Remaining gaps

The execution-risk-to-position-size and concentration-to-correlated-exposure rules now have bounded monotone helpers with a normalized `[0, 1]` input contract and regression tests. The concentration helper caps a correlated-exposure value supplied by a caller; it does not compute correlation or concentration from portfolio holdings. The inputs, trusted measurement sources, correlation model, and production-wide runtime authority remain open.

FD-08 remains `PARTIAL`. The local monotonicity rules are tested, while trusted measurement, correlation modeling, and immutable platform-wide hard-ceiling binding remain incomplete.

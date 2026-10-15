# State / Action Contract

The machine-readable state/action matrix is `schemas/state_action_matrix.csv`.

This is a policy baseline. Runtime guards may only tighten it; they must not widen a BLOCK into an ALLOW. Safety overrides therefore have authority above ordinary action policy.

For production, each action additionally requires compatibility validation, relevant TTL validation, risk/accounting guards and audit emission.

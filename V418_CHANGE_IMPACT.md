# V4.18 Change Impact

## Scope

V4.18 adds an aggregate authority over §177 M1–M30 and connects it to V4.17 compliance, V3.93 independent-review admission, V4.13 cryptographic review and the V3.94/V3.95 trust-anchor verification chain. The update is additive; it does not rewrite existing runtime order, risk, accounting, execution or recovery authorities.

## Data and event changes

A new `MACHINE_CHECK_READINESS_EVALUATED_V418` event records the decision ID, bundle and upstream compliance decision, canonical matrix hash, review/package/crypto fingerprints, blocker IDs/reasons, status, and fixed safety values (`production_ready: false`, `activation_flag: NOT_SET`). Event identity is deterministic. Reusing an existing decision ID with changed inputs fails closed.

## Compatibility

- V4.17 remains the upstream compliance authority.
- V3.93 remains the external-review admission contract.
- V4.13 remains the crypto review gate; V4.18 consumes its durable result rather than generating a signature.
- V4.18 does not treat internal pytest fixtures as operational evidence.
- Existing compliance rows and unresolved gaps are retained. This release does not auto-promote `TESTED`, `IMPLEMENTED` or `PARTIAL` to `VERIFIED`.

## Regression-test maintenance

Two pre-existing M7 champion-authority tests in `tests/v334_test_champion_authority.py` were brought into line with the current fail-closed API: the missing-authority assertion now expects the combined gate/evidence/bundle-authority rejection, and the former incomplete “positive” call is explicitly tested as rejected when Evidence Snapshot and Promotion Bundle authorities are absent. No production implementation behavior was loosened; the tests now reflect the already-required prerequisites.

## Operational effect

No network, subprocess, exchange mutation, credential issuance, runtime activation or live trading behavior is added. Without complete, genuinely external review artifacts and closed per-check gaps, the matrix remains `BLOCKED`.

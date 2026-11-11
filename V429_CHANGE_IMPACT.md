# V4.29 Change Impact

- Scope: final order-dispatch authority for risk, position, market data and causal TTL across current and legacy Testnet paths, plus reviewer-side external file access for GitHub governance signing, CI milestone identity, compliance matrix, and workflow contract validation.
- Modified code: `src/trading_platform/v311/dispatch_guard.py`, `v36/user_execution.py`, `v379/execution_parity.py`, `v380/order_adapter.py`, `v384/testnet_execution_activation.py`, `v385/controlled_testnet_submit.py`, and the V4.29 validation contract.
- New authority/helpers: `trading_platform.v429.external_file_safety` and `trading_platform.v429.workflow_contract`.
- Final dispatch now rejects missing risk/position/market/causal authorities and expired RiskDecision, intent, or request deadline before gateway invocation. V3.85 shares the same M1–M5 checks; older direct-submit adapters fail closed; V3.36 accepts only a guarded dispatcher.
- Champion promotion now requires durable PASS records for every required gate, binds the authorization to the exact gate runs and fingerprints, and revalidates them at registry promotion and LIVE activation. A changed or invalidated gate blocks reuse.
- V3.75 live/shadow inference now requires a durable artifact compatibility grant and rechecks the current seven-dimension report, version/hash binding and dependency invalidations before each prediction call. The V4.29 preflight and CI workflow include M14.
- M9's research boundary now inspects Python `__slots__`, mangled credential attribute names, and NumPy object arrays; direct `TuningDataView` construction applies the boundary before storing research rows.
- Safety properties: no-follow descriptor traversal, bounded regular-file reads, consistency checks during read, no-overwrite output creation, `0600` output permissions, and fail-closed behavior on unsupported platforms.
- Operational effect: the Testnet submit API now requires current durable authority evidence through the controlled path. Tests use fake gateways; no Testnet order, Production mutation or deployment activation is performed.
- Reversibility: revert V4.29-specific runner, workflow and signer/helper changes; retain the V4.28 recovery archive as the direct baseline.

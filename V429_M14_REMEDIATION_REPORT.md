# V4.29 M14 Runtime Compatibility Remediation

**Status:** `TESTED`; production inference integration and independent runtime review remain open.

## Finding

Deployment activation already required a durable compatibility authorization, but the V3.75 live/shadow decision runner could invoke its prediction callable without checking compatibility at runtime. An earlier deployment PASS therefore did not protect that direct execution seam against an expired, replaced, incompatible, unknown, or invalidated artifact context.

## Changes

- Added `CompatibilityGuardedArtifactExecutor`. It requires a durable compatibility authorization and dependency invalidation authority from the same event store, fetches the current compatibility report for each call, and validates the exact artifact ID/hashes, code/configuration/execution-model versions, report fingerprint, authorization window, event-chain integrity and dependency state before invoking the callable.
- Made the V3.75 live/shadow decision runner require this executor and an injected timezone-aware current-time provider. It checks compatibility before every injected pipeline stage. The V3.79 parity harness also checks compatibility before starting its backtest reference. Missing guard/clock, incompatible or unknown report, expired authorization, binding mismatch, invalidation, or malformed report stops before the affected callable runs.
- Expanded M14 coverage to every compatibility dimension (`runtime_input_schema`, `output_schema`, `feature_schema`, `configuration`, `dependencies`, `execution`, and `venue_rules`) with both `INCOMPATIBLE` and `UNKNOWN` results. Added proof that current compatibility is fetched again on each invocation and that expired grants do not reach the callable.
- Added M14 to the fixed V4.29 preflight impact set and CI workflow contract.
- Hardened backtest/live decision-trace comparison: only the supported trace version and non-empty immutable traces with unique ordered offsets and a valid content hash can pass. Comparison preserves duplicate rows when checking event parity and returns explicit validation errors for malformed or tampered traces.
- Added a bounded signed-model runtime seam: prediction-stage model objects expose their artifact ID and content hash, and the M14 executor requires those values to match the durable authorization before calling the model.
- Closed the local constructor bypass: only instances returned by the Ed25519-checking loader are marked signature-verified; direct construction and ordinary dataclass copies cannot predict, and the V3.75 M14 boundary rejects an unverified model before invoking it. Numeric conversion overflow in signed coefficients and runtime features also fails with a bounded model error.

## Verification boundary

V3.75 remains a decision-only live/shadow runner and does not submit orders. The V3.73 backtest engine still accepts injected pure stage functions. The new signed JSON model adapter is a local/tested inference format and must use the M14 executor with its loaded ID/hash. A production model service, trusted-key distribution/rotation, independent runtime review and deployment integration are not implemented. The trace comparator validates supplied trace integrity and parity evidence; it does not prove production inference or execution.

M14 remains `TESTED`, not `VERIFIED`. Tests use synthetic compatibility reports and local durable event stores. No Testnet/Production order or deployment was activated. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

The focused M14/model/parity/release regression passed **53 tests** on Windows/Python 3.14.7. The full V4.29 runner on package 3.61.27 passed **1,353 tests, 26 skipped**, with `RELEASE_HYGIENE=PASS`; `.audit/V428_MILESTONE_PREFLIGHT.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, zero blockers and **170 input hashes**. The signed model remains a local format: trusted-key distribution, production inference service, independent review and deployment integration remain open.

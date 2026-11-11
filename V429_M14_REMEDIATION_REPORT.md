# V4.29 M14 Runtime Compatibility Remediation

**Status:** `TESTED`; production inference integration and independent runtime review remain open.

## Finding

Deployment activation already required a durable compatibility authorization, but the V3.75 live/shadow decision runner could invoke its prediction callable without checking compatibility at runtime. An earlier deployment PASS therefore did not protect that direct execution seam against an expired, replaced, incompatible, unknown, or invalidated artifact context.

## Changes

- Added `CompatibilityGuardedArtifactExecutor`. It requires a durable compatibility authorization and dependency invalidation authority from the same event store, fetches the current compatibility report for each call, and validates the exact artifact ID/hashes, code/configuration/execution-model versions, report fingerprint, authorization window, event-chain integrity and dependency state before invoking the callable.
- Made the V3.75 live/shadow decision runner require this executor and an injected timezone-aware current-time provider. It checks compatibility before every injected pipeline stage. The V3.79 parity harness also checks compatibility before starting its backtest reference. Missing guard/clock, incompatible or unknown report, expired authorization, binding mismatch, invalidation, or malformed report stops before the affected callable runs.
- Expanded M14 coverage to every compatibility dimension (`runtime_input_schema`, `output_schema`, `feature_schema`, `configuration`, `dependencies`, `execution`, and `venue_rules`) with both `INCOMPATIBLE` and `UNKNOWN` results. Added proof that current compatibility is fetched again on each invocation and that expired grants do not reach the callable.
- Added M14 to the fixed V4.29 preflight impact set and CI workflow contract.

## Verification boundary

V3.75 remains a decision-only live/shadow runner and does not submit orders. The V3.73 backtest engine still accepts injected pure stage functions; no production model inference adapter is implemented in this checkout. Any future artifact loader or production inference integration must use the guarded executor at its execution boundary and bind its actual runtime versions. This report does not claim that such a production path exists.

M14 remains `TESTED`, not `VERIFIED`. Tests use synthetic compatibility reports and local durable event stores. No Testnet/Production order or deployment was activated. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

The focused Windows/Python 3.14.7 compatibility, live/shadow, invalidation and release-contract regressions passed **65 tests**. The mandatory V4.29 runner passed with **1,224 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; its preflight was `READY_FOR_MILESTONE`, `allowed=true`, included M14 and reported no blocking reasons.

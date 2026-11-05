# V4.29 Final Dispatch Authority Remediation

**Status:** `TESTED`; independent review and external operational evidence remain open.

## Findings and changes

The final order dispatcher accepted missing risk, position, market-data, or causal-TTL ledgers from direct callers. The runtime integration passed position, market, and causal ledgers but did not pass the durable RiskDecision ledger. Risk freshness and order-request deadline checks were also conditional on that optional ledger, so an omitted ledger skipped both checks.

The final pre-dispatch boundary now fails closed:

- Every submit requires a durable RiskDecision ledger and revalidates its action, binding, exposure, truth hash, and TTL immediately before any side effect or replay result.
- Intent validity and the committed request deadline are checked on every submit.
- Every order requires a current, verified position authority. Risk-increasing OPEN/INCREASE orders also require fresh market data and a valid causal artifact chain.
- `ExecutionRuntimeIntegration` accepts and passes the durable risk ledger to the final dispatcher. Missing authority is returned as a denied dispatch and never calls the gateway.
- The V4.29 preflight and CI workflow now mark M1–M5 as impacted and bind the changed dispatcher, runtime, tests, and report into the local preflight contract.

## Verification

The focused final-dispatch regression suite passed **43 tests** across V3.11, V3.12, V3.17, V3.18, V3.20, and V3.21. The full mandatory V4.29 runner passed on Python 3.14.7: **1,190 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; the preflight recorded `READY_FOR_MILESTONE` with all M1–M5 controls included. Tests cover missing authorities, expired RiskDecision, expired intent/request, UNKNOWN position, and no gateway call on every denied case.

Only fake gateways were used. No exchange request, Testnet order, or Production action was sent.

M1–M5 remain `TESTED`, not `VERIFIED`. Independent review, live venue reconciliation/market evidence, and operational evidence are still required. This remediation does not establish production readiness or authorize LIVE trading. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

# V4.29 M1–M5 Alternate Transport Remediation

**Status:** `TESTED`; independent review and external venue evidence remain open.

## Finding

The final V3.11 dispatcher enforced durable RiskDecision, position, market-data and causal-TTL authority, but older order-submit entrypoints could reach a Testnet gateway without passing through it. V3.79/V3.80 adapters and the V3.84 activation adapter each exposed a direct submit method. V3.85's controlled first-order runner also sent directly after validating a caller-supplied snapshot. V3.36's ambiguous-submit helper accepted a raw exchange-submit callable.

## Changes

- Extracted the shared M1–M5 checks into `assert_final_dispatch_authorities`; V3.11 and V3.85 both invoke it immediately before a replay or external submit.
- V3.85 now requires durable RiskDecision, position, market-data and causal-TTL ledgers. It compares the pre-trade snapshot's risk fingerprint and truth binding with the durable decision and checks requested exposure before recording the dispatch claim.
- V3.79/V3.80 direct adapter submission and the V3.84 activation-only adapter fail closed with `CONTROLLED_SUBMIT_AUTHORITY_REQUIRED`; they still provide deterministic request mapping where needed.
- V3.36 now accepts the guarded dispatcher, verifies it owns the same committed bridge and client order ID, and performs only read-only reconciliation after an ambiguous submit. The raw submit callable is no longer an accepted dispatch path.
- Added regressions for missing and expired RiskDecision, missing position/market/causal authorities, expired market evidence, snapshot risk/exposure mismatch, and bypass attempts through legacy adapters. All fake gateways fail the suite if called on a denied case.

## Verification

Focused Windows/Python 3.14.7 regressions across V3.11, V3.18, V3.36, V3.79, V3.84, V3.85, V3.86, V3.87 and V3.89: **89 passed**. The mandatory V4.29 full runner is recorded separately after completion.

No Testnet or Production order was sent. The gates remain `TESTED`, not `VERIFIED`; the changes do not provide independent review, live venue evidence, or production readiness. `external_evidence=false`, `production_ready=false`, `activation_flag=NOT_SET`.

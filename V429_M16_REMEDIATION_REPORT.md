# V4.29 M16 Configuration Authority Remediation

**Status:** `TESTED`; independent review and broader production integration remain open.

## Scope

The V3.43 configuration ledger already records resolved and conflicting configuration fingerprints durably. This remediation closes the final application boundaries where the durable resolution had not yet been required: the V3.12 Testnet dispatch integration and V3.25 deployment activation.

## Changes

- `OperationalTruth` carries a configuration resolution ID and candidate fingerprint in its canonical hash; `AuthorityDecision` preserves both values.
- Durable order request and commit records serialize and restore those bindings, including compatibility with older records that lack the fields.
- Before an order reaches the Testnet gateway, `ExecutionRuntimeIntegration` requires an injected configuration ledger, a resolution ID and the current configuration candidates. It checks the live resolution, expiry and fingerprint, then confirms that the committed authority references the same resolution. Any failure returns a denial before submission.
- Before CANARY or LIVE deployment authorization, `DeploymentActivationLedger` requires a resolved, durable configuration record matching the configuration binding in Operational Truth. The activation record stores the binding and references its ledger event.
- Every later activation validation checks that the bound configuration is still resolved and unexpired. Missing, conflicting, changed and expired configuration therefore fail closed at activation and reuse.

## Verification

Focused tests for Testnet dispatch, market freshness, durable request/commit restoration, deployment activation, transition replay, dependency invalidation, compatibility, integrity and reconciliation passed: **84 passed** on Windows/Python 3.14.7 (5 November 2026). The tests use local fake gateways and do not submit exchange orders.

## Remaining boundary

M16 remains `TESTED`, not `VERIFIED`. Independent review and evidence that every production configuration source is wired into this authority remain required. This report does not establish external evidence, production readiness or permission to activate LIVE trading.

`external_evidence=false`, `production_ready=false` and `activation_flag=NOT_SET` remain in force.

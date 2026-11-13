# V4.29 M20 Risk Reservation Remediation

## Requirement

M20 prohibits consuming a risk reservation more than once. MASTER PROMPT §68–§71 and §152 also require atomic reservation, a valid reservation for risk-budget orders, an accounting binding, and a consistent restart/recovery path.

## Local changes

- `DurableRiskReservationBook.reserve` now holds a SQLite `BEGIN IMMEDIATE` across the budget replay/check and reservation append. Concurrent connections cannot both reserve the same remaining budget.
- The V3.11 final dispatcher blocks OPEN/INCREASE submits without reconciled persistent accounting, a persistent reservation book, and an exact intent/risk-decision/accounting-hash match. V3.12 exposes those authorities as constructor inputs.
- The V3.85 controlled Testnet submit boundary applies the same reservation and accounting checks, requires a disk-backed dispatch event store, and rejects a pre-trade snapshot whose accounting projection hash is stale.
- The risk reservation flow is recorded in `docs/71_V5_RISK_RESERVATION_FLOW.md` and `schemas/v5_risk_reservation_flow.csv`; FD-23 has a stable §179 reference.
- The V4.29 fixed preflight and hosted workflow include M20, the concurrent reservation regression, and final-dispatch coverage.

## Verification

- Focused dispatch, reservation, traceability, release-contract, and milestone-contract tests: **146 passed**.
- Fixed V4.29 runner: **1,410 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight `READY_FOR_MILESTONE`, `allowed=true`, pipeline `PASS`, zero blockers, M20 included, and 237 input hashes. The report is `.audit/V429_M20_RISK_FINAL_20261112.json`.
- This is local evidence only: `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.

## Limits

This validates local SQLite behavior with synthetic data and fake gateways. It does not establish production-wide shared-store wiring, external accounting truth, authenticated operator/reviewer identity, venue exactly-once behavior, or production readiness. No live order, production mutation, or deployment was performed.

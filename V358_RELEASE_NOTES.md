# V3.58 Release Notes

Requirement/acceptance scope: Master Prompt §178 — END-TO-END ACCEPTANCE TEST.

V3.58 adds a deterministic, offline end-to-end acceptance runner spanning:

Historical Data → Validation → Feature → Target → Baseline → Model → Prediction → Signal → Opportunity → Portfolio → Risk → Intent → Order Simulation → Execution → Fill → Position → Accounting/P&L → Audit → Replay → Evidence → Gate.

The acceptance harness also checks the §178 mandatory properties:

- deterministic identifiers;
- provenance across stage boundaries;
- reproducibility across two identical runs;
- failure injection through duplicate-fill protection;
- restart/recovery through durable risk and intent restoration;
- rollback through a separate order lifecycle cancel path.

The runner is strictly offline. It uses a deterministic simulated Testnet transport and makes no external network request.

`production_ready` remains `FALSE`; passing §178 acceptance is not by itself equivalent to VERIFIED or PRODUCTION_READY under the Master Prompt.

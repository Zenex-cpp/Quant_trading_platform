# V3.28 Release Notes

V3.28 adds the durable execution half of the final deployment state-transition contract.

Changes:
- new `trading_platform.v328` durable transition execution ledger;
- separate append-only `DEPLOYMENT_STATE_TRANSITION_EXECUTED` event;
- deterministic activation planning in `DeploymentOrchestrator.plan_activate()`;
- crash/restart replay of the immutable post-state from the execution event;
- no capability consumption before durable execution evidence exists;
- capability consumption remains single-use and occurs only after the durable execution event is committed;
- idempotent retries reuse the persisted execution record;
- chain-head and event-hash binding fail closed on incompatible replay;
- the EXECUTED record must reference an existing matching V3.26 authorization event;
- compliance M10/M11/M28 evidence updated.

Verification: **415/415 tests passed**.
No live/Testnet exchange request or real credential was used.
`production_ready = FALSE`.

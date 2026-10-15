# V3.98 Change Impact

Purpose: add the final application-level critical-promotion readiness boundary for §156/§186 and rollback evidence.

Changes:
- add `v398.critical_promotion` authority;
- require production + CRITICAL scope;
- require dual human approval;
- require independent human review bound to exact bundle and dependency checkpoint;
- require accepted trust-anchor, security/monitoring and DR evidence for the same release;
- require externally attested rollback evidence bound to the exact bundle, snapshot and rollback target;
- verify rollback reviewer signature using V3.95 trust-anchor contract;
- persist a durable, idempotent readiness decision;
- fail closed on missing, expired, conflicting or mismatched evidence.

No production/live authorization is manufactured. External operational evidence remains external.

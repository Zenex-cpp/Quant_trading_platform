# V4.6 Open-Gaps Delta

## Closed at application level
- durable gate reuse decision based on explicit dependency checkpoint;
- fail-closed invalidation of stale gates after dependency changes;
- prevention of silent resurrection of an old gate after dependency incident revalidation;
- revision-aware audit/idempotency for repeated gate checks.

## Still open / blocking
- actual independent security assessment execution;
- actual production monitoring, paging and on-call drill;
- actual infrastructure network segmentation evidence;
- actual secret-store deployment and rotation evidence;
- actual backup/restore/failover/failback evidence;
- actual authenticated Testnet mutation evidence;
- actual independent human approval operation;
- actual production rollback exercise evidence;
- production operational/security sign-off;
- materialization and independent review of real external evidence artifacts;
- independently signed revalidation witness over real operational evidence;
- operational execution of V4.4/V4.5/V4.6 controls against real evidence.

These remain `NOT_VERIFIED` and do not become verified through application tests alone.

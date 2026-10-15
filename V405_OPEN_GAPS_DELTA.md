# V4.5 Open-Gaps Delta

## Closed at application level
- V4.4 revocation is now connected to the durable evidence-dependency invalidation ledger.
- Revoked witnesses can propagate a fail-closed impact to dependent evidence, gates, candidates and promotions when those relationships are represented in the graph.
- Revocation propagation is durable and idempotent.
- The integration fails closed when the revoked witness is absent from the dependency graph.

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
- an independently signed revalidation witness over real operational evidence;
- operational execution of the V4.4/V4.5 controls against real evidence.

These remain `NOT_VERIFIED` and are not manufactured by V4.5.

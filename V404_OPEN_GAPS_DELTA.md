# V4.4 Open-Gaps Delta

## Closed at application level
- explicit durable revocation state for external-readiness revalidation;
- fail-closed reuse prevention after revocation;
- exact witness-fingerprint binding during revocation;
- exact bundle/evidence-snapshot/release-hash binding during revocation;
- signed reviewer authorization with reviewer/operator separation;
- idempotent revocation persistence;
- explicit distinction between `REVOKED` and `EXPIRED`;
- hash-chain verification before and after revocation.

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
- an actual independently signed revalidation witness over real operational evidence;
- operational execution of the V4.4 revocation control against real evidence.

These remain `NOT_VERIFIED` and are not manufactured by V4.4.

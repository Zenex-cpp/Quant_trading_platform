# V4.3 Open-Gaps Delta

## Closed at application level
- immutable event-hash binding for a revalidation witness;
- independent reviewer/operator separation;
- Ed25519 signature and signature-hash verification;
- bounded revalidation validity window;
- explicit non-synthetic review-evidence reference gate;
- EventStore chain verification at revalidation admission;
- idempotent durable revalidation event;
- hard expiry check for subsequent consumers through `assert_fresh()`;
- no-network/no-process-escape contract for the revalidation authority.

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
- materialization and integrity of real external evidence artifacts;
- an actual independently signed revalidation witness over real operational evidence.

These remain NOT_VERIFIED and are not manufactured by V4.3.

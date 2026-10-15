# V3.98 Critical Promotion Readiness Runbook

This is an application-level gate. It does not create human approval or external operational evidence.

Required inputs:
1. exact PromotionBundle + immutable Evidence Snapshot;
2. two distinct human approvers;
3. independently executed Human Review authorization;
4. accepted Trust Anchor Attestation;
5. accepted Security/Monitoring Readiness;
6. accepted DR Attestation;
7. external rollback attestation for the exact bundle;
8. current dependency checkpoint with no invalidation.

Decision:
- all required inputs valid -> `VERIFIED` readiness event;
- any missing/expired/mismatched input -> `REJECTED` and no promotion authority.

For a real production exercise, preserve the signed external evidence references. Never place private keys or credentials in the package.

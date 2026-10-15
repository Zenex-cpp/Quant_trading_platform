# V3.96 Change Impact

Changed component: external operational DR evidence admission.

Affected components:
- v3.95 trust-anchor/reviewer chain;
- operational readiness evidence;
- production-readiness compliance matrix;
- external evidence governance.

Safety impact:
- no new order authority;
- no change to RiskEngine limits;
- no change to Testnet mutation path;
- new acceptance boundary can only add VERIFIED external DR evidence after hard checks pass.

Invalidation triggers:
- DR policy version/hash change;
- reviewer key revocation/expiry;
- RPO/RTO requirement change;
- backup/restore evidence hash change;
- recovery-proof invalidation;
- failover/failback evidence invalidation.

Required revalidation:
- rerun v3.96 contract tests;
- regenerate external attestation;
- obtain independent review again when a critical dependency changes.

# V3.95 Change Impact

Changed component: trust-anchor external attestation boundary.

Affected components:
- V3.94 cryptographic attestation.
- V3.93 external review authority.
- production-readiness evidence chain.

New controls:
- registry snapshot hash binding;
- fingerprint-set equality;
- independent reviewer trust key;
- custody/ceremony evidence references;
- revocation drill evidence;
- external attestation acceptance ledger.

No historical evidence is modified. A new versioned evidence node and audit chain are created.

Open external gaps remain:
- real custody/HSM/PKI proof;
- real independent reviewer operation;
- actual external key ceremony evidence;
- infrastructure network segmentation proof;
- secret-store deployment/rotation proof;
- authenticated Testnet mutation;
- DR/backup/recovery operational evidence.

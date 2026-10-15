# V3.96 External DR Attestation Runbook

Purpose: transform real operational backup/DR exercise evidence into a machine-verifiable external attestation without placing secrets in the trading platform repository or evidence payload.

Required operational evidence:
1. immutable backup artifact identifier/hash;
2. restore execution log and resulting artifact/state hash;
3. measured RPO;
4. measured RTO;
5. failover evidence reference;
6. failback evidence reference;
7. recovery proof showing reconciled state, passed invariants, no unresolved critical issue and guards passing;
8. operator identity;
9. custodian identity;
10. independent reviewer identity and signed attestation;
11. reviewer key validity/revocation evidence.

Hard stop conditions:
- RPO > policy ceiling;
- RTO > policy ceiling;
- missing or synthetic evidence reference;
- recovery proof incomplete;
- reviewer equals operator or custodian;
- reviewer key inactive, expired, revoked, or out of scope;
- signature invalid;
- policy version/hash mismatch.

Never place private keys, API secrets, credentials, recovery seeds or vault values in the attestation payload.

A local application-level DR drill is not sufficient to mark production DR VERIFIED. The authority accepts external proof; it does not create that proof.

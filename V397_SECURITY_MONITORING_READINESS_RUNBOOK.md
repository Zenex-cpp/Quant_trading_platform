# V3.97 Security + Monitoring Readiness Runbook

Purpose: convert externally executed security and monitoring evidence into a machine-checkable readiness decision. This runbook does not generate external proof.

## Security assessment prerequisites
- assessment is external to the platform producer;
- exact release artifact hash is recorded;
- approved methodology version is recorded;
- CRITICAL findings = 0 and HIGH findings <= policy ceiling;
- evidence and remediation references are immutable and non-synthetic;
- independent reviewer signs the canonical attestation with a currently trusted key.

## Monitoring prerequisites
- all required critical signal codes are covered;
- alert delivery latency <= policy ceiling;
- on-call response <= policy ceiling;
- unresolved CRITICAL alert count <= policy ceiling;
- drill, paging and dashboard evidence references are real and non-synthetic;
- independent reviewer signs the canonical attestation with a distinct trusted key.

## Admission sequence
1. Freeze the exact release artifact hash.
2. Acquire external security assessment package.
3. Acquire external monitoring/paging drill package.
4. Verify both policy snapshots and hashes.
5. Verify both reviewer trust anchors and Ed25519 signatures.
6. Verify release-artifact hash equality.
7. Verify reviewer/source independence.
8. Admit both attestations atomically at the readiness authority boundary.
9. Preserve the immutable event-store evidence and chain verification result.
10. Only then allow the downstream readiness gate to consume the authority.

## Failure policy
Any mismatch, expiry, missing coverage, open hard finding, invalid signature, synthetic evidence reference, reviewer conflict, or hash mismatch => `NOT_VERIFIED` / deployment blocked.

## Current status
The application-level authority is TESTED. Actual external security assessment, production paging/on-call drill, and independent operational sign-off remain NOT_VERIFIED.

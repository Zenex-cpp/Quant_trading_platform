# V3.92 Release Notes

V3.92 adds the machine-checkable production secret-store operational contract for
Master Prompt M157 and the outstanding secret-store review gap.

Implemented:
- production secret backend must be an attested non-development backend;
- environment and in-memory development stores are forbidden as production
  secret backends;
- secret lease TTL is bounded and machine-checkable;
- lease expiry/revocation/consumption fail closed;
- backend attestation has an explicit validity window and reviewer reference;
- evidence/review payloads reject likely raw secret fields;
- configuration fingerprints are deterministic and secret-free.

Non-goals:
- no claim of a deployed Vault/KMS/cloud-secret-manager instance;
- no production credential retrieval;
- no live/Testnet mutation.

Verification status:
The application contract is TESTED. External secret-store operational proof and
independent review remain NOT_VERIFIED and continue to block production readiness.

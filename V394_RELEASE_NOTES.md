# V3.94 Release Notes

V3.94 adds a machine-checkable cryptographic attestation verifier for the V3.93 independent-review path.

Implemented:
- real Ed25519 signature verification using the runtime `cryptography` implementation;
- canonical signature binding to exact package ID/hash, review ID/hash and scope;
- versioned trust-anchor metadata with validity windows, revocation state and scope allowlist;
- deterministic public-key fingerprint verification;
- signature-byte SHA-256 verification;
- durable append-only verification event in EventStore;
- restart-safe and idempotent verification;
- fail-closed behavior for tampered subjects, invalid signatures, expired/revoked keys,
  scope mismatch, fingerprint mismatch, missing trust-anchor attestation and hash mismatch;
- secret-free audit payloads.

Non-goals:
- no production private key is generated, stored or committed;
- no claim that the configured trust-anchor registry is externally attested;
- no HSM/PKI infrastructure proof;
- no live/Testnet mutation;
- no production-readiness override.

The runtime now proves the cryptographic operation itself. External trust-anchor custody,
key ceremony, PKI/HSM evidence and independent external attestation remain required before
this control can be marked VERIFIED for production.

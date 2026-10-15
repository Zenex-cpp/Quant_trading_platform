# V3.95 Release Notes

V3.95 adds an external trust-anchor attestation intake boundary above V3.94.

## Purpose

The runtime must never upgrade the V3.94 trust-anchor control from TESTED/NOT_VERIFIED to VERIFIED merely because local cryptographic verification succeeds. V3.95 accepts an externally produced attestation package only when the exact runtime trust-registry snapshot is covered by independent reviewer evidence, signed by a separately trusted reviewer key, and accompanied by custody, ceremony and revocation-drill references.

## Safety properties

- Exact registry version/hash binding is mandatory.
- Exact authorized anchor-fingerprint set is mandatory.
- Custody and key-ceremony evidence references are mandatory and cannot be synthetic/demo references.
- Revocation drill must prove that a revoked anchor is blocked.
- Reviewer must be distinct from the custodian.
- Reviewer key must be active, scoped, unexpired and fingerprint-valid.
- Reviewer signature is Ed25519 and is verified before acceptance.
- Private key/secret fields are rejected from the attestation payload.
- Accepted attestations are durably audited and idempotent.
- Expired, revoked, mismatched or unsigned attestations fail closed.

## Verification status

The implementation and in-process cryptographic verification are TESTED.
External custody, actual ceremony/HSM evidence and independent external reviewer operation remain external evidence requirements and are NOT_VERIFIED by this release.

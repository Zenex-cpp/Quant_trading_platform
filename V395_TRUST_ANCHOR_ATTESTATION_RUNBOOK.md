# V3.95 Trust-Anchor Attestation Intake Runbook

## Purpose

Convert the V3.94 trust-anchor control from `TESTED / NOT_VERIFIED` to `VERIFIED` only after an independently produced external attestation is available.

## Required package

1. Exact runtime trust-registry version.
2. Exact runtime trust-registry SHA-256.
3. Complete authorized production review-key fingerprint set.
4. Custody evidence reference.
5. Key ceremony / protected-key-origin evidence reference.
6. Revocation drill evidence proving a revoked anchor is blocked.
7. Independent reviewer identity.
8. Independent reviewer public-key trust record and fingerprint.
9. Detached Ed25519 signature over the canonical attestation body.
10. Validity window for the external attestation.

## Hard rules

- Never provide a private signing key to the platform.
- Never put private key material in repository, logs, evidence, source or configuration.
- Registry hash must equal the runtime registry hash exactly.
- Fingerprint set must equal the runtime authorized set exactly.
- Reviewer and custodian must be distinct actors.
- Reviewer key must be ACTIVE, valid and correctly scoped.
- Revocation drill must pass before acceptance.
- Synthetic/demo references are forbidden.
- Expired, revoked or malformed evidence remains `NOT_VERIFIED`.

## External execution

The ceremony must be performed outside the application trust boundary. The application only ingests and verifies the resulting public evidence. The ceremony operator must not ask the research or execution runtime to generate, store or expose private signing material.

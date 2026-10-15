# V3.94 Trust Anchor / Key Ceremony Runbook

Purpose: produce the external evidence required to upgrade the V3.94 trust-anchor control
from `TESTED / NOT_VERIFIED` to `VERIFIED`.

Required evidence package:
1. Trust-anchor registry version and exact registry hash.
2. Public key fingerprint for every authorized production review key.
3. Key provenance and ownership record.
4. Generation/key ceremony record or equivalent protected-key-origin evidence.
5. Evidence that private signing material is not present in research, repository, logs or runtime bundles.
6. Activation timestamp, validity period and authorized scopes.
7. Revocation/rotation procedure and tested revocation evidence.
8. Independent reviewer identity and attestation over the registry hash/fingerprint set.
9. Cryptographic signature verification result for a real externally produced review envelope.
10. Recovery evidence showing that an invalid/revoked anchor blocks new verification.

Hard rules:
- Never place a private key in this repository or evidence package.
- Never log private key material or credential material.
- A trust anchor with UNKNOWN, REVOKED or expired status must fail closed.
- The exact registry hash/fingerprint set reviewed by the independent party must equal the registry used at runtime.
- Production verification remains blocked until the external review/signature evidence is accepted by the V3.93 and V3.94 authorities.

The application can verify Ed25519 signatures, but this runbook is intentionally external:
proof of custody, key ceremony, HSM/PKI controls and independent attestation cannot be
manufactured by the application itself.

# V3.94 Change Impact

## Changed component
`trading_platform.v394.cryptographic_attestation`

## Requirements covered
Master Prompt §113–§176, especially evidence integrity, external-review governance,
artifact provenance, production readiness and the VERIFIED definition.

## Dependencies
- V3.93 `ExternalReviewAttestationV393`
- V3.361 evidence package canonical hashing
- V21 append-only EventStore
- Python `cryptography` Ed25519 implementation

## Safety impact
Positive and fail-closed. A V3.93 review is not cryptographically admitted unless the
exact package/review subject is signed by an active, unexpired, non-revoked trust anchor
whose fingerprint and scope match.

## Downstream impact
No execution authority is widened. Existing V3.84–V3.90 Testnet gates are unchanged.

## External evidence still required
- external custody/attestation of trust anchors;
- actual PKI/HSM or equivalent operational evidence;
- independent review of the trust-anchor lifecycle;
- authenticated Testnet mutation evidence;
- network, secret-store, backup/restore, DR, security and monitoring operational evidence.

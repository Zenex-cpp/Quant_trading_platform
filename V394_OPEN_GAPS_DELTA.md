# V3.94 Open-Gaps Delta

The runtime now performs actual Ed25519 signature verification over a canonical evidence/review binding.

Still open / blocking:
- external trust-anchor custody and attestation is not present in this runtime;
- PKI/HSM/key-ceremony evidence is not present;
- independent external review evidence is not present;
- infrastructure network-segmentation proof is not present;
- secret-store deployment/rotation proof is not present;
- Testnet authenticated mutation evidence is not present;
- backup/restore and DR operational evidence remain external;
- security assessment and operational monitoring evidence remain external.

No historical gap register is mutated; this is a versioned delta.

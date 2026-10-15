# V4.25 Recovery Build — Lineage and Evidence Limits

V4.25 is built from the actual V4.24 Recovery Build archive available in this runtime (SHA-256 `5ad06a5cf86efda3d2c9046c9cbea1374967fefb19826148b472acd294dcbfba`). V4.24 itself documented that the original canonical V4.23 source archive was unavailable and that its source lineage was recovered from V4.18. V4.25 therefore preserves and carries forward that recovery caveat; it does not claim canonical byte-for-byte lineage from V4.23.

The tests for provider capture use synthetic API responses and temporary Ed25519 keys. They validate parser, scope, identity, artifact-hash and signature mechanics only. No target repository was connected or queried by this build, no hosted workflow was run as part of this turn, and no production trust anchor is configured.

Canonical adoption requires replaying/rebasing onto the original V4.23 tree if it is restored, then running this mandatory entrypoint in the actual target GitHub repository, capturing current read-only provider evidence at the exact protected HEAD, obtaining an independent review/signature, and verifying the signed snapshot with an independently approved public-key trust anchor.

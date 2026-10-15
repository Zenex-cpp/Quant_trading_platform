# V3.40 Release Notes

## M13 — No activation after critical reconciliation mismatch

V3.40 closes the remaining activation boundary for reconciliation.

A durable `ReconciliationAuthorityLedger` records every reconciliation observation, including the canonical REST/stream hashes and a fingerprint of the reconciliation diff. A deployment activation must reference a current green reconciliation authorization for the same scope.

A later RED, BLOCKED or UNKNOWN observation supersedes the prior green authorization and immediately makes an already recorded deployment activation unusable. A new green observation is required before another activation can be authorized.

Deployment activation now persists the reconciliation authorization binding and re-validates it during final activation/transition, including after restart. Legacy V3.26 and V3.28 activation consumers are covered by the same gate.

No external exchange/Testnet network calls or production credentials are used by this release.

# V4.29 M10 Durable Event Store Thread Safety

**Status:** `TESTED`; independent storage tamper review remains open.

## Finding

The append-only SQLite event store used a connection restricted to its creating thread and had no per-connection serialization. Concurrent calls from credential resolution and revocation could fail on SQLite's thread check or interleave access to one connection. Credential resolution event IDs also collided when the same credential was resolved twice at the same timestamp, which could collapse separate access records into one idempotent ledger event.

## Changes

- EventStore now permits use across threads and serializes all connection operations with a reentrant lock. Event iteration holds the lock while streaming rows, avoiding a whole-ledger memory copy.
- Credential resolution and revocation share a vault lock, so an in-flight resolution finishes its audit append before a concurrent revocation can persist and delete the secret.
- Resolution and denial audit events include unique request identifiers, preserving distinct attempts that occur in the same millisecond.
- Added concurrent append/hash-chain coverage, same-timestamp resolution coverage, and a controlled resolution/revocation race regression.

## Verification boundary

The focused credential/backend, credential-boundary, ledger-concurrency, secret-store policy and release-contract suite passed **62 tests** on Windows/Python 3.14.4. The full V4.29 runner on package 3.61.16 passed **1,306 tests, 26 skipped**, with `RELEASE_HYGIENE=PASS`; final preflight `.audit/V429_M9_M10_CREDENTIAL_FINAL2_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, and no blockers. The lock protects one EventStore instance in one process; it does not replace independent storage tamper review, backup/DR, or cross-process operational controls. M10 remains `TESTED`, not `VERIFIED`.

`external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

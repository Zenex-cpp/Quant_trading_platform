# V3.82 Release Notes

## Added
- Authenticated Testnet user-stream session boundary.
- USER_STREAM control transport for `userDataStream.start/ping/stop`.
- Private WebSocket stream transport with fail-closed state handling.
- listen-key rotation handling on keepalive.
- Runtime-only API key handling; no credential values in evidence.
- Production-host rejection at configuration/network-policy boundary.

## Verification
- Local deterministic authenticated-session tests.
- Keepalive success/failure.
- listen-key rotation.
- `listenKeyExpired` fail-closed behavior.
- malformed/unknown event fail-closed behavior.
- live authenticated connectivity remains `NOT_VERIFIED` unless operator configuration and external network are available.

## Scope boundary
V3.82 does not submit any order. Order mutation remains outside this session layer.

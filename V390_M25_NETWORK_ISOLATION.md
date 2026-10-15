# V3.90 M25 Network Isolation Closure

M25 states that the research network cannot reach production trading endpoints. The
same invariant is extended to the credentialed Testnet boundary: a Testnet request
must not be able to leave the exact approved Testnet endpoint through ambient proxy
settings or redirect handling.

Machine-enforced rules:

1. Environment must be `TESTNET`.
2. REST requests must use `https://testnet.binancefuture.com`.
3. REST requests may not specify a non-default port or userinfo.
4. WebSocket endpoints are separately allowlisted to `fstream.binancefuture.com`.
5. Non-empty HTTP/HTTPS/ALL proxy environment variables are blocked.
6. The urllib opener is created with an empty proxy map.
7. Redirects are rejected rather than followed.
8. The exact target is revalidated on every request.
9. The boundary is injected beneath the existing V3.80/V3.85 controlled submit path.

This closes the application-level egress boundary. It does not claim OS-level routing
proof; host firewall, VPC/NACL, container network policy or equivalent infrastructure
evidence remains an operational deployment requirement.

# V3.91 Verification Report

Baseline before change: 843/843 tests PASS.

V3.91 isolated tests: 11/11 PASS.

Full regression: 854/854 tests PASS.

The release implements the application-side network-segmentation contract for M25.

Verified locally:

- deny-by-default policy
- research -> production denial
- research -> Testnet denial
- Testnet -> production denial
- production -> Testnet denial
- exact-host-only allowlists
- wildcard rejection
- TLS-only transport schemes
- no new mutation authority

Infrastructure-level verification remains OPEN because this repository cannot prove
an actual VPC/NACL, host firewall, security group, container network policy or routing
table from application tests alone.

The V391 evidence explicitly records `infrastructure_proof=NOT_VERIFIED`.
No external network mutation was performed.

Production readiness: FALSE.

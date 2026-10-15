# Trading Platform v3.83 — Release Notes

## Purpose

Close the next operational-readiness gap after v3.82 by adding a read-only connectivity preflight without fabricating live exchange evidence.

## Added

- `trading_platform.v383_connectivity`.
- TESTNET-only endpoint validation.
- DNS resolution gate.
- Read-only `/fapi/v1/time` probe.
- Client/server clock-integrity gate.
- Explicit connectivity status semantics.
- Evidence runner `run_v383_connectivity_preflight.py`.
- Versioned registry `schemas/v383_connectivity_registry.csv`.

## Verification

- 769/769 repository tests PASS.
- v3.83: 6/6 PASS.
- Runtime preflight: `NOT_VERIFIED` due DNS resolution failure in the current execution environment.
- No mutating API call.
- No credentials consumed.

## Non-goals

v3.83 does not claim authenticated Testnet connectivity, does not submit orders, and does not promote production readiness.

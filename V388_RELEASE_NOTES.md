# V3.88 Release Notes

V3.88 adds an evidence-closed operational boundary for the first real Testnet order.

The release introduces an immutable execution evidence bundle that joins preconditions, single dispatch, order/user-data observations, REST/WS reconciliation, accounting reconciliation and closure into one hash-bound causal record.

The bundle rejects duplicate dispatch evidence, correlation mismatches, non-terminal order states, non-green reconciliation, missing accounting evidence and secret-bearing metadata. The release runner remains probe-only; no real Testnet mutation is performed during verification.

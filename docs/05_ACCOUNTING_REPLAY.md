# 05 — Accounting and Replay Foundation

Accounting states: UNRECONCILED, RECONCILED, ADJUSTED, UNKNOWN.
UNKNOWN blocks new risk until resolved.

Core invariant:
`equity_change = P&L + fees + funding + deposits_withdrawals + other_valid_account_events`
where the exact applicable account model is versioned.

Replay stores:
- event_offset;
- snapshot_version;
- state_hash;
- deterministic processing order;
- provenance/version references.

Replay is an audit reconstruction, not a trading decision override mechanism.

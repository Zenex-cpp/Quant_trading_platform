# Risk Budget and Reservation

Risk budget scopes: SYSTEM, PORTFOLIO, STRATEGY, MODEL, TRADE, ORDER.

The durable reservation projection records `allocated`, `reserved`, `consumed`, `released`, `expired`, `overridden`, and `remaining`, where `remaining = allocated - reserved - consumed`. Released, expired, and overridden amounts are terminal audit totals; they are not added again to the available budget.

Reservation lifecycle: requested → reserved → consumed/released/expired.

A reservation is consumed exactly once.
No order may consume a risk reservation that does not exist or has already been consumed.

Every risk-increasing dispatch requires a persistent reservation bound to the exact intent, risk decision, requested amount, and reconciled accounting projection hash. The reservation is consumed before transport. An ambiguous transport result keeps it consumed until reconciliation.

See [the V5 risk reservation flow](71_V5_RISK_RESERVATION_FLOW.md) for actors, event names, transition rules, recovery, and known integration limits.

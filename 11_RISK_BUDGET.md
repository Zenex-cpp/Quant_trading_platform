# Risk Budget and Reservation

Risk budget scopes: SYSTEM, PORTFOLIO, STRATEGY, MODEL, TRADE, ORDER.

Reservation lifecycle: requested → reserved → consumed/released/expired.

A reservation is consumed exactly once.
No order may consume a risk reservation that does not exist or has already been consumed.

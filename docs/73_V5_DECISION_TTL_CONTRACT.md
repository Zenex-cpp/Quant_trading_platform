# V5.0 Decision TTL Contract

MASTER PROMPT §20 requires a validity window on Prediction, Signal, Opportunity
Score, Portfolio Allocation Decision, Risk Decision, and Order Intent. The
canonical policy is `schemas/v5_decision_ttl_policy.csv`.

Every window is timezone-aware and satisfies `valid_from < expires_at`. A
downstream artifact is usable only while it and every required upstream artifact
are valid. Its expiry may not be later than an upstream expiry. Expiry has the
precedence `UPSTREAM_EXPIRES_FIRST` and blocks new risk; it is never converted to
a warning or renewed implicitly.

`ValidWindow`, `DecisionTTL`, and the durable V3.333 causal TTL ledger enforce
these rules locally. The registry requires the complete six-class policy and
timezone-aware windows. The policy is specification and local-runtime evidence
only; it does not assert synchronized clocks or production deployment wiring.

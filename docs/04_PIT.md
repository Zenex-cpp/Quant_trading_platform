# 04 — Point-in-Time / Data Availability Contract

Every source-derived object exposes:
- source_event_time;
- available_at;
- availability_source;
- publication_delay;
- revision_policy;
- first_published_version;
- revised_version;
- revision_timestamp.

Backtests consume the latest version known as-of the decision timestamp, not today's retroactive revision.
A value with `available_at > decision_time` is invalid for that decision.
Unknown availability semantics are operationally UNKNOWN and block safety-critical downstream use.

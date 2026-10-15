# V3.2 Release Notes

V3.2 closes the authorization/dispatch TOCTOU window with one-shot trade capabilities.

A capability binds the exact Operational Truth hash, requested risk, decision id, intent fingerprint and expiry. Commit revalidates the canonical truth, exact intent and capability freshness before routing; successful commit consumes the capability exactly once.

No exchange network execution is enabled by this release.

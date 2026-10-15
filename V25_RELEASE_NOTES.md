# V2.5 Release Notes

## Scope
V2.5 adds versioned drift/health monitoring and a fail-closed trading freeze.

## Delivered
- Detector configuration is versioned and fingerprintable.
- PSI and mean-shift detectors expose deterministic severity: NONE/WARNING/CRITICAL.
- Insufficient observations are critical.
- Missingness beyond the configured threshold is critical.
- Evidence freshness is enforced through explicit TTL and verification state.
- Missing/expired evidence, unhealthy streams, critical drift and degraded quality cannot increase risk; critical cases freeze trading.
- Freeze decisions carry report hash, assessment ID and a zero risk cap when blocked.

## Verification
176 tests passed. No live credentials used. No mutating exchange requests executed.

## Production status
NOT PRODUCTION READY.

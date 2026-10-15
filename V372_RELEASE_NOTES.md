# V3.72 Release Notes

V3.72 adds an application-level disaster-recovery exercise covering:

- durable SQLite WAL checkpoint before backup cutover;
- disaster declaration with live state removed;
- clean restore from governed backup artifact;
- event-chain verification after restore;
- snapshot verification;
- deterministic suffix replay through GapRecoveryCoordinator;
- state/invariant equality proof;
- fail-closed RTO handling.

Evidence classification: `INTERNAL_TEST_EVIDENCE`.

This does not close the V3.59 disaster-recovery operational evidence gap and does not constitute cross-region infrastructure DR, production RPO/RTO, failover, or incident-response evidence.

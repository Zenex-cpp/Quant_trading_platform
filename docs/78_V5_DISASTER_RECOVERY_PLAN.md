# V5.0 Disaster Recovery Plan

`schemas/v5_disaster_recovery_plan.csv` defines RPO/RTO targets, backup custody,
restore cadence, integrity checks, fail-safe behavior, and the external evidence
still required for state, evidence, configuration, and recovery audit stores.

The local `BackupRestoreService` and V3.372 drill verify allowlisted archive
creation, manifest hashes, safe restore, replay, and RPO/RTO enforcement with
synthetic data. A failed backup, restore, hash check, or target is blocking. The
`EXTERNAL_*` columns are explicit gates: local drills do not establish encrypted
custody, independent review, operator availability, or production RPO/RTO.

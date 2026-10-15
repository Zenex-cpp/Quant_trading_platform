# V4.11 Operational Evidence Protocol

## Purpose

V4.11 adds a machine-checkable completeness boundary for the nine operational-readiness evidence classes already required by the V3.60/V4.10 readiness path.

This release does **not** create external evidence, does **not** verify external evidence, and does **not** change `production_ready`. A complete dossier receives only `READY_FOR_EXTERNAL_REVIEW`.

## Required classes

`LIVE_VENUE`, `NETWORK_SEGMENTATION`, `SECRET_STORE`, `BACKUP_RESTORE`, `DISASTER_RECOVERY`, `SECURITY_REVIEW`, `MONITORING`, `ROLLBACK`, `INDEPENDENT_REVIEW`.

Each class has a protocol describing the objective, required artifact kinds, and required manifest fields. The manifest must contain exactly one item per required class, all explicitly marked `EXTERNAL`, with time validity, content hash, artifact references, and an attestation reference.

## Fail-closed rules

A manifest is rejected when it has missing classes, duplicate evidence IDs, non-external provenance, synthetic/demo/fixture references, missing class-specific fields, invalid time windows, invalid content hashes, sensitive credential material, a mismatched manifest hash, or a package identity conflict.

## Boundary

`READY_FOR_EXTERNAL_REVIEW` is not `VERIFIED` and is not `PRODUCTION_READY`. Independent external review, actual operational execution, cryptographic/trust-anchor validation where required, recovery proof, and human approval remain external requirements.

The authority persists only the manifest identity, scope, hash and evidence-ID set for deterministic revalidation. It never mutates readiness evidence into `VERIFIED` state.

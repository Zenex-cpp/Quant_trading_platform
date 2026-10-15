# V4.11 Release Notes

## Change

Introduced `OperationalEvidenceManifestAuthorityV411` as the machine-checkable admission boundary for operational-readiness evidence.

## What is now enforced

- exactly the nine required operational evidence classes are present;
- each evidence item is explicitly `EXTERNAL`;
- synthetic/demo/fixture sources are rejected;
- class-specific artifact and reference fields are mandatory;
- evidence time windows and content hashes are validated;
- sensitive credential-like fields are forbidden from the manifest;
- the full manifest has a deterministic hash;
- package identity is idempotent and cannot be rebound to different content.

## What is not claimed

V4.11 does not assert external evidence is genuine merely because a manifest declares it. It does not perform network calls, venue mutations, production changes, security assessments, disaster recovery exercises, or human approvals. It does not change `production_ready`; that state remains blocked until the external requirements are actually satisfied and independently reviewed.

## Verification

- V4.11 focused tests: 12/12 PASS
- full repository regression: 1011/1011 PASS
- production readiness: FALSE

## Package

- governed manifest entries: **1,489**
- production readiness: **FALSE**

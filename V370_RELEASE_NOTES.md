# V3.70 Release Notes

## Scope
V3.70 adds a deterministic repository security/supply-chain hygiene drill at `src/trading_platform/v370/security_review_drill.py`.

## Master Prompt alignment
- §153 SECURITY THREAT MODEL: repository-level secret and network-surface checks.
- §157 SECRET MANAGEMENT: release artifacts must not contain obvious secret material or secret-like files.
- §154 NETWORK SEGMENTATION: research source surface is checked for direct network clients and production venue endpoints.
- §174 PRODUCTION READINESS: security evidence is made machine-checkable at the application/repository layer.

## Evidence boundary
`V370_SECURITY_REVIEW.json` is `source_kind=INTERNAL` and `scope=REPOSITORY_RELEASE_ARTIFACT`.
It does not replace an independent security assessment, production secret-store review, infrastructure egress review, or supply-chain audit.

`production_ready` remains `FALSE`.

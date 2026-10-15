# V3.62 Release Notes

## Scope

Governance/integrity correction following Master Prompt v5.0.

## Changes

- Corrected the §178 acceptance semantic contract: `acceptance_passed` now represents §178 acceptance success.
- `production_ready` is no longer derived from the §178 acceptance runner and is explicitly `FALSE` at that boundary.
- Historical V3.58 acceptance evidence is intentionally not rewritten.
- Synchronized current project metadata to V3.61.0.
- Added an explicit repository source-of-truth document identifying `trading_platform/` as the canonical runtime package for this release.
- Current release documentation now reports the verified suite size and preserves the production-readiness boundary.
- Release-manifest guidance excludes generated caches and bytecode from new release artifacts.

## Safety statement

This release does not create production evidence, production approval, live venue evidence, or autonomous production authorization.

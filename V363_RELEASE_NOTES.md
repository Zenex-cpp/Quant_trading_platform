# V3.63 Release Notes

## Scope

Governed completion of the repository source-layout migration required by the V3.62 source-of-truth contract.

## Changes

- Promoted the complete runtime package into `src/trading_platform/`.
- Removed the duplicate root-level `trading_platform/` package.
- Added explicit setuptools `src`-layout discovery in `pyproject.toml`.
- Updated pytest import configuration to resolve the package from `src`.
- Added machine-checkable source-layout tests.
- Updated repository source-of-truth documentation to record the completed migration and its invariants.
- Regenerated release verification and manifest evidence.

## Compatibility boundary

The Python distribution version remains `3.61.0`, preserving the existing package-version contract. V3.63 is the repository/release train identifier for this governed migration.

## Safety statement

This release does not create production evidence, production approval, live venue evidence, or autonomous production authorization.

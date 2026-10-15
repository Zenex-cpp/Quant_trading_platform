# V3.63 Verification Report

## Change scope

V3.63 completes the previously deferred repository source-layout migration from the V3.62 source-of-truth contract.

## Pre-change finding

The repository contained two Python package trees:

- `trading_platform/`: 272 Python source files and the declared canonical runtime tree.
- `src/trading_platform/`: 202 Python source files and the tree consumed by the existing setuptools wheel build.

The two trees were therefore both incomplete and semantically divergent. Repository tests and distributed artifacts could verify different code.

## Corrective action

- Synced the complete canonical runtime package into `src/trading_platform/`.
- Removed the duplicate root-level `trading_platform/` package.
- Configured setuptools discovery explicitly for `src`.
- Configured pytest to import from `src`.
- Updated the one filesystem-path regression test that inspected the old root package path.
- Removed generated build/egg-info/cache artifacts from the release tree.
- Added source-layout regression tests and a dedicated compliance record.

## Migration integrity

The 272 Python source files from the former canonical root package were compared by relative path and SHA-256 against the new `src/trading_platform/` tree:

- only in former root: 0
- only in new src tree: 0
- content mismatches: 0

Internal Python import names remain `trading_platform.*`; only repository/package discovery changed.

## Verification gates

- Source package exists under `src/trading_platform/`: PASS.
- Root-level `trading_platform/` package absent: PASS.
- Setuptools discovery explicitly targets `src`: PASS.
- Runtime import resolves from `src/trading_platform`: PASS.
- Full automated suite: **PASS — 648 tests**.
- Offline wheel build: PASS — `trading_platform-3.61.0-py3-none-any.whl`.
- Wheel Python file count: **272**.
- Wheel contains no `src/` package tree, bytecode or cache artifacts: PASS.
- Installed-wheel runtime import: PASS.
- Acceptance success remains distinct from production readiness: PASS.
- Historical V3.58 acceptance evidence unchanged: PASS — SHA-256 `32a236349a3d62fc96655194e34eade3bcaa15966a82ec9a93d951500262b0d6`.

## Evidence hashes

Historical V3.58 acceptance SHA-256 is recorded in the verification gates above.

## Reproducible build

Two independent offline wheel builds with `SOURCE_DATE_EPOCH=1700000000` produced the same SHA-256:

`c0314d3082bc04c747bb9deb82910622297e953bf9befb5fe96bca84f52036fa`

## Production readiness

`production_ready = FALSE`.

This release is a repository/package-layout correction only. It does not introduce real venue evidence, independent human approval, production credentials, or live-trading authorization.

# 00 — Repository Source of Truth

## Canonical runtime source

The canonical runtime Python package is:

`src/trading_platform/`

The repository now uses an explicit `src/` layout. The package-discovery configuration in `pyproject.toml` and the pytest import path both point to `src/`. The release wheel and installed package are built from this tree.

## Completed migration

V3.63 completes the previously deferred source-layout migration described by V3.62. The migration copied the complete canonical runtime tree into `src/trading_platform/`, removed the duplicate root-level runtime package, made setuptools discovery explicit, and reran the full verification suite.

Required migration evidence:

- package/discovery configuration change;
- import-path verification;
- full test rerun;
- manifest regeneration;
- wheel reproducibility/build evidence;
- dependency-graph impact review.

All are recorded in `V363_VERIFICATION_REPORT.md`.

## Legacy root path

`trading_platform/` at repository root is no longer a runtime source. A root-level package directory must not be reintroduced. Historical manifests and release evidence that reference the previous path remain immutable and are not rewritten.

## Machine checks

Release verification must fail when:

- `trading_platform/` exists at repository root as a Python package;
- `src/trading_platform/` is missing;
- setuptools discovery does not resolve packages from `src`;
- the built wheel contains a second package tree;
- import resolution does not load `trading_platform` from `src/trading_platform`.

## Release hygiene

Release manifests must exclude generated Python bytecode, pytest caches, build directories and other non-source transient files. Historical manifests remain immutable even when they contain such files.

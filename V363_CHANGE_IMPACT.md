# V3.63 Change Impact Record

## Change

`ROOT_RUNTIME_PACKAGE -> SRC_RUNTIME_PACKAGE`

## Changed component

- `pyproject.toml` package discovery
- runtime package location
- pytest import path
- repository source-of-truth documentation
- filesystem-path regression test

## Affected components

- setuptools wheel construction
- repository test import resolution
- source-layout verification
- release manifest contents

## Unchanged semantic dependencies

Python import names remain `trading_platform.*`. No module API namespace was renamed. The runtime module set was copied from the former canonical root package without semantic transformation.

## Dependency graph impact

The change affects repository/package path resolution only. Internal dependency edges between `trading_platform.*` modules remain unchanged because absolute package import names are unchanged.

## Invalidated historical artifacts

None. V3.58 and earlier historical evidence/manifests are immutable and were not rewritten.

## Revalidation required

- package discovery: COMPLETE
- import-path verification: COMPLETE
- full test suite: COMPLETE
- clean-source wheel build: COMPLETE
- installed-wheel import verification: COMPLETE
- manifest regeneration: COMPLETE

## Deployment impact

`production_ready` remains `FALSE`. No production deployment or production approval is changed by this repository-layout migration.

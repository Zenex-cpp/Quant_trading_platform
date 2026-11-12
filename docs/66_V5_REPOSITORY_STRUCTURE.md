# V5.0 §179 Repository Structure

This is the navigable map of the current repository. Its machine-readable directory inventory is `schemas/v5_repository_structure.csv`; `tests/test_v5_repository_structure.py` compares that inventory with every top-level directory, every direct runtime namespace, and every direct test group. Additions or removals in those locations must update the inventory in the same change.

## Canonical paths

| Path | Purpose |
| --- | --- |
| `src/trading_platform/` | Sole canonical Python package and runtime source. |
| `tests/` | Unit, integration, contract, security, operations, and failure-injection coverage. Version folders align tests with version-scoped modules. |
| `docs/` | Architecture, contracts, release notes, verification reports, and runbooks. |
| `schemas/` | Machine-readable API contracts, requirements matrices, registries, and policy tables. |
| `scripts/` | Fixed validation and acceptance runners, audits, data import, and repository governance utilities. |
| `config/` | Repository governance and trust configuration. |
| `ops/` | Operator-facing tooling. |
| `evidence/` | Evidence records and templates, with each record's verification scope stated by its owning report. |
| `.github/` | CI workflows and repository automation policy. |
| `verification/` | Versioned verification output and supporting records. |

The immediate directories inside `src/trading_platform/` are split between shared domain packages (accounting, contracts, data, events, evidence, execution, gates, model, promotion, research, risk, security, state, and related services) and version-scoped `vNN` namespaces. Shared modules own cross-version domain primitives. Version namespaces retain milestone-specific authorities and adapters. Tests are the contract for compatibility across the two layers.

The inventory lists all 148 direct runtime namespaces and all 87 direct test groups, including sparse historical version namespaces. Root-level `vNN` folders and `v33_test` are retained validation/evidence snapshots; they are not canonical import paths. The version-specific root-file families for prompts, release notes, manifests, evidence, and compliance records are categorized in the inventory.

## Repository boundary

`MASTER PROMPT.txt` is the normative project specification. `README.md` and `pyproject.toml` describe the package and entrypoints. The current Python package is built only from `src/` through setuptools package discovery. A root-level `trading_platform/` package is prohibited.

`.git/` is Git metadata. `.audit/` holds local milestone reports and databases and is deliberately outside the versioned repository map and release commits. Do not copy local audit outputs into source manifests or erase them as part of ordinary source changes.

This artifact describes repository organization and source ownership. It does not certify that each module's operational controls or external dependencies are production-ready.

# V3.65 Release Notes

V3.65 hardens source-release artifact hygiene under the Master Prompt reproducibility and deployment-governance requirements.

## Change
- Added `scripts/validate_release_hygiene.py` as a reusable machine-checkable validator.
- Release hygiene rejects `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.pyc`, and `.pyo` artifacts.
- Clean release staging is now performed before manifest generation.
- Python package version remains `3.61.0`; V3.65 is the repository/release train identifier.
- No production capability, exchange credential, network route, or live execution capability is added.

## Scope
This change is limited to artifact packaging and reproducibility hygiene. Trading, risk, accounting, execution, deployment-authority, and evidence semantics are unchanged.

## Reproducible build contract

The governed wheel build uses an explicit `SOURCE_DATE_EPOCH`. Two independent builds with `SOURCE_DATE_EPOCH=1700000000` produced the same SHA-256. Uncontrolled timestamped builds are not treated as reproducible evidence.

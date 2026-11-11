# V4.29 M9 Research Credential Boundary Remediation

**Status:** `TESTED`; production credential-store and process-isolation evidence remain open.

## Finding

The research credential scanner rejected direct credential types, mappings, lists and ordinary instance dictionaries, but did not inspect Python `__slots__` or NumPy object arrays. A production credential wrapped in either form passed `assert_research_safe` and could cross the research argument boundary. `TuningDataView` also accepted direct row inputs without applying that boundary itself.

## Changes

- Extended the scanner to inspect inherited slot declarations and Python-mangled slot names. Credential-bearing slot names and nested credential/reference/vault objects fail closed.
- Extended the scanner to traverse NumPy arrays whose dtype contains Python objects, including structured object fields. Numeric arrays remain unexpanded.
- Made direct `TuningDataView` construction validate train, validation and OOS inputs before storing them.
- Added regressions for slotted wrappers, mangled secret attribute names, NumPy object arrays, and direct tuning-data construction. Added M9 to the fixed V4.29 preflight impact set and CI workflow contract.
- Configured pytest to collect the retained legacy credential test module as part of the normal suite; historical manifests continue to reference the same path.

## Verification boundary

The Windows/Python 3.14.7 focused credential, tuning, holdout and release-contract regressions passed **56 tests**. The mandatory V4.29 runner passed with **1,240 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, with M9 and M14 impacted and no blocking reasons. This verifies application-level argument screening and the role-gated in-process vault; it does not provide operating-system process isolation or an external secret manager. The production credential store and process boundary must be separately integrated and evidenced before M9 can be `VERIFIED`.

No production credential was configured or resolved during these tests. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.

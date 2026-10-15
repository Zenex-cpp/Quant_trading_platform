# V3.97 Change Impact

Changed component: external operational readiness evidence boundary.

Added:
- `src/trading_platform/v397/readiness_attestation.py`
- `tests/v397/test_security_monitoring_readiness.py`
- `tests/v397/test_v397_source_contract.py`

Downstream impact:
- promotion/readiness must not infer production security or monitoring readiness from internal drills alone;
- release artifact hash is a common binding across both external evidence families;
- reviewer independence is mandatory between security and monitoring attestations.

No existing order, risk, position, accounting, Testnet, or production mutation authority is widened by V3.97.

External evidence remains NOT_VERIFIED until independently supplied and accepted through the new authority.

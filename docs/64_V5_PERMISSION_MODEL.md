# V5.0 §155 Permission Model

This document specifies the role-to-capability boundary for the nine permission categories in `MASTER PROMPT.txt` §155. The complete 9 × 9 decision matrix is published in `schemas/v5_permission_matrix.csv` and is checked against runtime policy by `tests/test_security_permissions.py`.

| Role | Granted capabilities |
| --- | --- |
| RESEARCH | RESEARCH, TRAINING, BACKTEST |
| TRAINING | TRAINING |
| BACKTEST | BACKTEST |
| SHADOW | SHADOW |
| CANARY | CANARY |
| PRODUCTION_TRADING | PRODUCTION_TRADING |
| DEPLOYMENT | DEPLOYMENT |
| CONFIGURATION | CONFIGURATION |
| SECURITY_ADMIN | SECURITY_ADMIN, CONFIGURATION |

Unknown role names and non-enum capability values are denied. Unlisted role/capability pairs are denied. Production trading does not grant deployment, configuration, or security administration. Security administration grants configuration management, but does not grant deployment or production trading. Research is limited to research, training, and backtesting.

The credential vault applies this split: `CONFIGURATION` or `SECURITY_ADMIN` can register, rotate, and revoke credentials; only `PRODUCTION_TRADING` can resolve current runtime credential material. Credential references are checked for identity, version, validity, status, and fingerprint, and management or access events are audited. Historical ledger events retain their recorded actor role for backward-compatible replay.

## Scope and limits

The matrix enforces role-to-capability decisions only. The repository does not yet provide a platform-wide resource entitlement system that binds every grant to a tenant, account, instrument, strategy, or deployment object. Individual services must validate their own resource identity and state; this is implemented for production credential references, but it is not a universal resource-level authorization layer. Caller identity and role assignment also require a trusted external identity provider. These gaps keep FD-44 **PARTIAL** in the §179 traceability register.

This permission model does not authorize an operation by itself. Ordinary state, evidence, risk, approval, compatibility, deployment, and dispatch gates continue to apply.

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

The credential vault applies this split: `CONFIGURATION` or `SECURITY_ADMIN` can register, rotate, and revoke credentials; only `PRODUCTION_TRADING` can resolve current runtime credential material. Production construction requires an injected authorization provider. Each operation passes its capability and exact credential resource to that provider; the caller cannot assert its own production role. Successful register, revoke, and resolve ledger events record the provider's authenticated actor ID and decision ID, while the opaque identity token is never stored. Historical ledger events retain their recorded actor role for backward-compatible replay. Caller-role authorization remains available only through the explicit test factory.

## Scope and limits

The matrix enforces role-to-capability decisions only. The credential vault now supplies a resource-scoped integration boundary, but this repository does not provide the trusted identity provider or its role/entitlement data. It also does not yet bind grants for every tenant, account, instrument, strategy, or deployment object across the platform. These gaps keep FD-44 **PARTIAL** in the §179 traceability register.

This permission model does not authorize an operation by itself. Ordinary state, evidence, risk, approval, compatibility, deployment, and dispatch gates continue to apply.

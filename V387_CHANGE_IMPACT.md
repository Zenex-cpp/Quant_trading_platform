# V3.87 Change Impact

changed_component -> V387 first-order safety boundary.

Affected components: V386 operator session, V385 controlled submit, V384 activation, V383 connectivity evidence.

Invalidated historical artifacts: none. V3.83-V3.86 remain immutable.

New verification requirement: first-order marketability proof is required at the final pre-submit boundary.

Deployment impact: `production_ready=FALSE` and `TESTNET_EXTERNAL_EXECUTION=NOT_VERIFIED`.

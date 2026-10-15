# V3.91 Change Impact

## Safety
Adds a directional, deny-by-default network-segmentation contract above the existing
application egress controls.

## Network
Defines exact hostname sets for RESEARCH, TESTNET_EXECUTION and PRODUCTION_TRADING;
wildcards and cross-environment endpoint overlap are rejected.

## Execution
No new mutation authority or exchange transport is introduced. The contract is a
precondition for deployment-level network policy review.

## Evidence
`V391_NETWORK_SEGMENTATION_EVIDENCE.json` is internal application-policy evidence.
It explicitly records `infrastructure_proof=NOT_VERIFIED`.

## External status
No external network mutation is performed by V3.91. Production readiness remains FALSE.

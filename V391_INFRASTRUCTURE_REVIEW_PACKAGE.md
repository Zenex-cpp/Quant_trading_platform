# V3.91 Infrastructure Network Segmentation Review Package

This package is a review template, not proof of deployed infrastructure.

Required external evidence:

1. Network architecture showing isolated RESEARCH, TESTNET_EXECUTION and
   PRODUCTION_TRADING segments.
2. Host-firewall / VPC security-group / NACL / container NetworkPolicy rules proving
   the required directional denies.
3. Evidence that DNS and routing cannot bypass the intended segmentation.
4. Evidence that production trading credentials are unavailable from RESEARCH and
   TESTNET_EXECUTION segments.
5. Independent reviewer identity, decision, timestamp and signature/hash.
6. Post-change connectivity tests showing intended allows and forbidden paths blocked.

Until those artifacts exist, `infrastructure_proof=NOT_VERIFIED` and
`production_ready=FALSE`.

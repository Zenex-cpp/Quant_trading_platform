# V3.91 Release Notes

V3.91 adds the machine-checkable network-segmentation contract required to turn the
remaining M25 infrastructure gap into an explicit deployment evidence item.

The policy is deny-by-default, uses exact hostnames only, rejects wildcard routes,
and enforces directional separation between RESEARCH, TESTNET_EXECUTION and
PRODUCTION_TRADING. Research cannot reach venue endpoints, the Testnet execution
zone cannot reach production venue endpoints, and the production zone cannot reach
Testnet endpoints.

V3.91 does not claim OS/VPC/container routing proof. The release therefore keeps
production readiness FALSE until an actual infrastructure control and independent
review evidence are attached.

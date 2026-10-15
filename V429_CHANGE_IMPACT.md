# V4.29 Change Impact

- Scope: reviewer-side external file access for GitHub governance signing, CI milestone identity, compliance matrix, and workflow contract validation.
- Modified code: `scripts/sign_github_governance_evidence.py`, V4.28 workflow-validator delegation, and the active GitHub Actions workflow.
- New authority/helpers: `trading_platform.v429.external_file_safety` and `trading_platform.v429.workflow_contract`.
- Safety properties: no-follow descriptor traversal, bounded regular-file reads, consistency checks during read, no-overwrite output creation, `0600` output permissions, and fail-closed behavior on unsupported platforms.
- Operational effect: none. No network calls, remote repository mutations, Testnet mutation, deployment activation, or Production mutation are added by V4.29.
- Reversibility: revert V4.29-specific runner, workflow and signer/helper changes; retain the V4.28 recovery archive as the direct baseline.

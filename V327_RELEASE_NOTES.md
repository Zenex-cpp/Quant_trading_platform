# V3.27 Release Notes

V3.27 hardens the final deployment activation capability introduced in V3.26.

## Added

- Capability validity window (`valid_from`, `expires_at`).
- Unique capability identity per issuance.
- Capability single-use consumption after a successful activation transition.
- Explicit time validation at the V3.28 activation primitive.
- Dedicated V3.27 capability-hardening tests.

## Changed

- The activation issuer is no longer exposed as the public `issue_activation_capability` API; the production path uses the internal issuer only through V3.25/V3.26 authority.
- V3.26 transition authorization now persists the activation validity window and passes it into the protected capability.
- Direct forged capabilities remain invalid because the internal capability secret is not externally constructible through the public constructor.
- Top-level package version is aligned to `3.27.0`.

## Boundary

This closes accidental/public API bypasses and stale-capability reuse inside the Python process. It does not claim protection against a fully compromised Python runtime or distributed deployment atomicity across external infrastructure.

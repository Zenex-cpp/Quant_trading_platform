# V3.93 External Review Package Contract

This package defines the minimum external artifact required to admit a critical
production-readiness evidence package into the independent-review path.

Required review facts:
- `review_id`
- `scope`
- exact `subject_ids` covering the evidence package and every evidence item
- `reviewer_id`
- `reviewer_role=INDEPENDENT_REVIEWER` or an equivalent governed role
- producer / owner / approver identities
- `decision=ACCEPT`
- `reviewed_at_ms`, `expires_at_ms`
- independent `source_system` and `source_ref`
- `signature_ref`
- `signature_hash` (SHA-256 formatted)
- `signature_verification=EXTERNALLY_VERIFIED`
- deterministic `review_hash`

The application verifies structure, scope, hashes, validity, independence and
provenance. It does **not** verify PKI/HSM authenticity itself; that remains an
external operational evidence item.

Expected external evidence:
1. signed review document or equivalent controlled artifact;
2. reviewer identity and organizational authority;
3. signature verification record;
4. exact evidence-package hash reviewed;
5. review timestamp and validity window;
6. conflict-of-interest/independence statement.

Until those external artifacts exist, this contract is TESTED, not VERIFIED.

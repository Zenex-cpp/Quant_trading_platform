# V4.27 Recovery Extension — Strict Provider Capture Boundaries

## Scope

This extension hardens the GitHub governance snapshot path inherited from the available V4.25 Recovery archive. It does not connect to GitHub, configure a trust anchor, or turn local fixture tests into external evidence.

## Strict Base64 handling

GitHub content responses may contain whitespace-wrapped Base64. The decoder removes whitespace and then uses strict alphabet/padding validation. Non-ASCII characters, invalid alphabet characters, incorrect padding, empty decoded content, an unexpected content type/encoding, or a mismatched path are rejected.

## Bounded audit artifacts

The capture helper accepts only the two expected audit artifact files:

- `V425_MILESTONE_PREFLIGHT.json`: at most 16 MiB.
- `V425_MILESTONE_PREFLIGHT.sqlite3`: at most 64 MiB.
- Combined limit: 80 MiB.

The capture script checks file size before reading, performs a bounded read, and rejects a size change between stat and read. Symlink/path-escape checks remain fail-closed.

## Evidence boundary

V4.27 tests use synthetic provider responses and boundary fixtures. They prove parser/limit behavior only. They do not prove repository protection, actual CODEOWNERS semantics, hosted Actions success, reviewer identity, trust ceremony, or production readiness.

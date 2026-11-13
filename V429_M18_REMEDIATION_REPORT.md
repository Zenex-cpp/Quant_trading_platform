# M18 remediation — transitive evidence invalidation

**Status: `TESTED`; not `VERIFIED` or production-ready.**

## Implemented

- Dependency changes now propagate to a fixed point across artifact graph nodes, evidence `dependencies` and `source_refs`, gates, candidates, and promotions. Evidence that consumes previously affected evidence is included even when it is not represented as a node in the artifact graph.
- The durable invalidation record lists every affected registry object and a deterministic `required_revalidation` set instead of a generic `REVALIDATE` marker. A path with registered dependents is marked `BLOCK_OR_REVALIDATE`; an empty supplied registry is reported as `NO_REGISTERED_DEPENDENT_OBJECT`.
- The V4.29 compliance matrix, fixed runner, workflow contract and CI impacted-requirement set include M18.
- Focused graph, durable invalidation, M18 snapshot, M27 holdout, M30 dependency, revocation and human-review regressions passed **53 tests**.

## Remaining evidence

- Closure covers the graph and registries supplied to each invalidation call. It cannot discover dependencies omitted from those inputs or infer active deployments because no authoritative production-wide registry is provided.
- Production graph completeness, signed source evidence, independent review and live promotion/deployment integration remain unverified. M18 stays `TESTED`.

No exchange calls, credential access, deployment activation or production mutation occurred.

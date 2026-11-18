# V5.0 Gate Dependency Matrix

`schemas/v5_gate_dependency_matrix.csv` is the exhaustive gate dependency graph
for research, promotion, recovery, and live activation. It makes the prompt's
promotion invariant machine-checkable:

`bundle_complete ∧ compatibility_pass ∧ evidence_valid ∧ required_gates_pass ∧
approval_valid ∧ scope_valid ∧ artifacts_integrity_valid`.

The matrix is a directed acyclic graph. A gate cannot pass while a prerequisite is
missing, invalidated, or absent from the passed set. The loader checks the full
transitive prerequisite closure and required artifacts for every gate in that
closure. Failure actions are fail-closed and identify the affected scope. Existing promotion, artifact
integrity, dependency invalidation, recovery proof, and activation authorities are
the implementation references; the matrix does not claim that external reviewer
identity is configured.

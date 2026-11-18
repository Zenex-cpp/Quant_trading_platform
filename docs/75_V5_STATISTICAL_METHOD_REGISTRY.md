# V5.0 Statistical Method Registry

`schemas/v5_statistical_method_registry.csv` is the complete versioned inventory
of statistical methods currently exposed by this repository. Each row declares
assumptions, limitations, required inputs, output semantics, implementation
reference, and status. The loader requires unique `(method_id, version)`
identities and complete contracts.

All rows are `SPECIFICATION_ONLY`. The catalog includes current repository
methods and prompt-listed candidates that are explicitly marked
`implementation_not_present`; those candidate rows document requirements and
must not be treated as executable evaluators. The registry never turns a method
into a production-approved method and does not invent a performance threshold.
The durable V3.353 methodology authority is a separate runtime registration
ledger; it records a method before applicability is checked, and failed
assumptions produce `METHOD_NOT_APPLICABLE` and prevent execution.

Adding a method requires a new versioned row, an implementation reference, and a
contract test. Reusing an identity with different content is a conflict.

# Modelable Documentation

Start with the
[root README](https://github.com/ktjn/modelable/blob/main/README.md) for the
shortest installation and example path. The documentation set is intentionally
small; each document has one role.

## Use Modelable

- [Getting started and migration](getting-started.md): installation, editor
  setup, generated artifacts, and migration from existing schema formats.
- [Language reference](language-reference.md): `.mdl` syntax, types,
  projections, CEL, ownership, classification, and access metadata.
- [Tooling reference](cli-reference.md): CLI commands, LSP behavior,
  AI-assisted authoring, and development tooling.
- [Compiler reference](compiler-reference.md): emitters, generated artifacts,
  compatibility metadata, registry state, and distributed lineage.
- [Sample scenarios](https://github.com/ktjn/modelable/tree/main/samples):
  worked `.mdl` examples.

## Understand the Project

- [Architecture and system specification](architecture.md): authoritative
  product concepts, invariants, and current/deferred boundaries.
- [External integrations](integrations.md): shipped dbt/FHIR/ODCS drift
  workflows, local export targets, and non-committed integration research.
- [Maintainer and agent guide](maintainers.md): local gates, review policy,
  release process, and automation rules.

The [roadmap](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) is
directional. A deferred item is not committed until it has an issue and
accepted design. Project-level policy remains in
[GOVERNANCE.md](https://github.com/ktjn/modelable/blob/main/GOVERNANCE.md),
[CONTRIBUTING.md](https://github.com/ktjn/modelable/blob/main/CONTRIBUTING.md),
and [SECURITY.md](https://github.com/ktjn/modelable/blob/main/SECURITY.md).

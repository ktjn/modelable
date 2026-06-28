# Roadmap

Modelable's current release is a local compiler and language-server toolchain
for versioned, domain-owned model contracts. The roadmap is directional; an
item is not committed until it has an issue and an accepted design.

## Targeting 1.0

Modelable 1.0 stabilizes the local compiler and language-server toolchain.

**Stable at 1.0:** `.mdl` language, CLI commands (`validate`, `compile`,
`check`, `generate`, `attach`, `spec`, language server), all current generated
artifact formats (JSON Schema, TypeScript, C#, Java, Python, Rust, Go, SQL
DDL, dbt `schema.yml`, Markdown, FHIR R4 profile, OpenMetadata JSON,
OpenLineage event), compatibility and lineage reports, governance findings,
Apicurio JSON Schema push/pull, and the VS Code extension as a VSIX companion
artifact.

**Deferred from 1.0:** VS Code Marketplace distribution, live catalog or
governance synchronization, remote tracked-spec polling, runtime subscriptions
and materialization, distributed registry synchronization, and hosted
documentation.

Remaining public-alpha work before 1.0:

- Stabilize the `.mdl` language and diagnostics through external use.
- Improve compatibility, lineage, and governance reporting.
- Harden package distribution, editor installation, and contributor workflows.
- Add more real-world examples and migration guidance.
- Exercise and harden Apicurio JSON Schema artifact publish/pull with real
  registry deployments.
- Harden local catalog, lineage, and contract-interchange exports before adding
  live synchronization commands.

## Next

Recently shipped, still hardening:

- `modelable generate --from` now bootstraps `.mdl` models from dbt
  `manifest.json`/`schema.yml`, FHIR R4 `StructureDefinition`, and ODCS
  documents; continue hardening edge cases (complex FHIR types, dbt
  model-version selection, ODCS field-level nuance) as real usage surfaces
  gaps.
- `modelable attach`/`modelable spec` now track dbt/FHIR/ODCS drift with
  additive/breaking diffs; continue hardening beyond direct-element mapping
  (e.g. complex FHIR types, dbt semantic-layer constructs).
- FHIR R4 profile mapping covers Patient/Observation/Encounter with
  extension/slice mapping for Modelable-only fields and an HL7 FHIR
  Validator smoke; continue hardening deep/recursive structure coverage.
- OpenMetadata and OpenLineage local export are implemented; continue
  validating output against real catalog/lineage consumers before
  considering live synchronization.

Deferred, not yet started:

- Live catalog/governance synchronization to OpenMetadata/OpenLineage once
  local export has enough validation evidence for a specific deployment
  target.
- Remote tracked-spec polling and authenticated source access for dbt, FHIR,
  ODCS, and future external specifications (current support is local-file
  only).
- Additional artifact formats driven by concrete consumers.

## Later

- Runtime subscriptions, adapters, replay, and materialization.
- Distributed registry synchronization beyond the current file-first model.
- Hosted documentation and VS Code Marketplace distribution.

See [docs/architecture.md](docs/architecture.md) for the
product model and [GitHub issues](https://github.com/ktjn/modelable/issues) for
work that is ready for discussion or implementation.

# Roadmap

Modelable's current release is a local compiler and language-server toolchain
for versioned, domain-owned model contracts. The roadmap is directional; an
item is not committed until it has an issue and an accepted design.

## Current: public alpha

- Stabilize the `.mdl` language and diagnostics through external use.
- Improve compatibility, lineage, and governance reporting.
- Harden package distribution, editor installation, and contributor workflows.
- Add more real-world examples and migration guidance.
- Exercise and harden Apicurio JSON Schema artifact publish/pull with real
  registry deployments.
- Harden local catalog, lineage, and contract-interchange exports before adding
  live synchronization commands.

## Next

- Live catalog/governance synchronization after local OpenMetadata and
  OpenLineage exports have enough validation evidence for a specific deployment
  target.
- Remote tracked-spec polling and authenticated source access for dbt, FHIR,
  ODCS, and future external specifications.
- Brand-new model bootstrapping from dbt `manifest.json` / `schema.yml`, FHIR
  `StructureDefinition`, and ODCS documents beyond the current attach/spec
  drift workflows.
- FHIR R4 profile hardening for a small base-resource set, including stronger
  element mapping and validation against representative profiles.
- Additional artifact formats driven by concrete consumers.

## Later

- Runtime subscriptions, adapters, replay, and materialization.
- Distributed registry synchronization beyond the current file-first model.
- Hosted documentation and VS Code Marketplace distribution.

See [docs/architecture.md](docs/architecture.md) for the
product model and [GitHub issues](https://github.com/ktjn/modelable/issues) for
work that is ready for discussion or implementation.

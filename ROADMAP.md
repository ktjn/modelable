# Roadmap

Modelable's current release is a local compiler and language-server toolchain
for versioned, domain-owned model contracts. The roadmap is directional; an
item is not committed until it has an issue and an accepted design.

## Current: public alpha

- Stabilize the `.mdl` language and diagnostics through external use.
- Improve compatibility, lineage, and governance reporting.
- Harden package distribution, editor installation, and contributor workflows.
- Add more real-world examples and migration guidance.

## Next

- External artifact registry integration.
- Catalog and governance-system integration.
- Open Data Contract Standard interchange.
- dbt schema/source export and import (see
  [docs/integrations.md](docs/integrations.md)).
- FHIR R4 profile export and import for a small base-resource set (see
  [docs/integrations.md](docs/integrations.md)).
- Additional artifact formats driven by concrete consumers.

## Later

- Runtime subscriptions, adapters, replay, and materialization.
- Distributed registry synchronization beyond the current file-first model.
- Hosted documentation and VS Code Marketplace distribution.

See [docs/architecture.md](docs/architecture.md) for the
product model and [GitHub issues](https://github.com/ktjn/modelable/issues) for
work that is ready for discussion or implementation.

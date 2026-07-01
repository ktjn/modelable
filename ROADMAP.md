# Roadmap

Modelable's current release is a local compiler and language-server toolchain
for versioned, domain-owned model contracts. The roadmap is directional; an
item is not committed until it has an issue and an accepted design.

## 1.0 — shipped 2026-06-28

Modelable 1.0 stabilizes the local compiler and language-server toolchain.

**Stable at 1.0:** `.mdl` language, CLI commands (`validate`, `compile`,
`check`, `generate`, `attach`, `spec`, language server), all current generated
artifact formats (JSON Schema, TypeScript, C#, Java, Python, Rust, Go, SQL
DDL, dbt `schema.yml`, Markdown, FHIR R4 profile, OpenMetadata JSON,
OpenLineage event, ODCS), compatibility and lineage reports, governance findings,
Apicurio JSON Schema push/pull, and the VS Code extension as a VSIX companion
artifact.

**Deferred from 1.0:** VS Code Marketplace distribution, remote tracked-spec
polling, distributed registry synchronization, live OpenMetadata catalog
synchronization, and runtime subscriptions and materialization. These remain
future candidates until a fresh issue and accepted design define a concrete
implementation slice.

## Next

Recently shipped, still hardening:

- Hosted documentation is published at
  [ktjn.github.io/modelable](https://ktjn.github.io/modelable/) from `main`;
  continue treating broken docs builds and links as release-blocking issues.
- The public conformance fixture under `samples/conformance/` mirrors the
  formerly private release checks for contributor-facing smoke coverage.
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
- OpenMetadata and OpenLineage local export are implemented, and
  `modelable sync --lineage marquez` can post OpenLineage events to a
  Marquez-compatible endpoint with a live Testcontainers smoke; continue
  validating OpenMetadata output and hardening live catalog synchronization
  against real consumers.

Deferred candidates, not yet started:

- Live OpenMetadata catalog synchronization once local export has enough
  validation evidence for a specific deployment target and a follow-up issue.
- Remote tracked-spec polling and authenticated source access for dbt, FHIR,
  ODCS, and future external specifications (current support is local-file
  only).
- VS Code Marketplace distribution.
- Distributed registry synchronization beyond the current file-first model.
- Runtime subscriptions, adapters, replay, and materialization.
- Additional artifact formats driven by concrete consumers.

## Later

- Advanced runtime adapters, materializers, and distributed registry services
  after the deferred candidates above have accepted designs.

See [docs/architecture.md](docs/architecture.md) for the
product model and [GitHub issues](https://github.com/ktjn/modelable/issues) for
work that is ready for discussion or implementation.

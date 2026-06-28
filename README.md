# Modelable

Modelable is a compiler and language server for versioned, domain-owned data
models. Define canonical models and projections in `.mdl` files, then validate
their compatibility, inspect field-level lineage, detect governance gaps, and
generate artifacts for the systems that consume them.

> **Public alpha — targeting 1.0:** Modelable is usable and tested. The `.mdl`
> language, CLI, and generated output may still change before 1.0; see
> [1.0 stable surface](#10-stable-surface) below for what is in and out of
> scope. Breaking changes are documented in [CHANGELOG.md](CHANGELOG.md).

## Why Modelable?

Data contracts often become fragmented across application types, database
schemas, API definitions, and catalog metadata. Modelable keeps the semantic
contract in one versioned source and derives target-specific representations
without losing ownership, classification, lineage, or compatibility context.

```text
.mdl sources -> validate and resolve -> plan and govern -> generate artifacts
```

## Install

Modelable requires Python 3.14.

```bash
uv tool install modelable
modelable --version
```

For an isolated one-off command:

```bash
uvx modelable --help
```

Until `v0.5.0` is published, install from the repository:

```bash
uv tool install "modelable @ git+https://github.com/ktjn/modelable.git@main#subdirectory=cli"
```

## Define a model

```text
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii email?: string
    displayName: string
  }
}
```

Save the definition as `customer.mdl`, then validate and compile it:

```bash
modelable validate customer.mdl --strict
modelable compile customer.mdl --target json-schema --out generated/schema
modelable compile customer.mdl --target typescript --out generated/types
```

## Capabilities

- Parse and validate versioned models, projections, annotations, and workspace definitions.
- Resolve exact versions and compatible version ranges.
- Detect additive and breaking contract changes and affected projections.
- Trace projection fields to canonical source fields.
- Report structurally missing access and classification metadata.
- Expand automatic database, request, reply, and event projections.
- Generate JSON Schema, Markdown, TypeScript, C#, Java, Python, Rust, Go, SQL
  DDL, dbt `schema.yml`, FHIR R4 profile, OpenMetadata JSON, and OpenLineage
  event artifacts.
- Provide diagnostics, completion, hover, navigation, references, rename, formatting, and other editor features through the language server.
- Import or assist with models through optional LLM provider integrations.

The local compiler is the supported alpha surface. Apicurio JSON Schema
artifact publish/pull is available for derived artifacts. Catalog publishing,
distributed synchronization, OpenLineage runtime event collection, and runtime
materialization remain roadmap work.

## 1.0 stable surface

Modelable 1.0 stabilizes the local compiler and language-server toolchain.

**In scope for 1.0:**

- `.mdl` language: syntax, types, projections, ownership, classification, and
  access metadata.
- CLI: `validate`, `compile`, `check`, `generate`, `attach`, `spec`, and the
  language server.
- Generated artifacts: JSON Schema, TypeScript, C#, Java, Python, Rust, Go,
  SQL DDL, dbt `schema.yml`, Markdown, FHIR R4 profile, OpenMetadata JSON, and
  OpenLineage event formats.
- Compatibility, lineage, and governance report output.
- Apicurio JSON Schema registry artifact push/pull.
- VS Code extension shipped as a VSIX companion artifact with the 1.0 release.

**Deferred from 1.0:**

- VS Code Marketplace distribution (post-1.0).
- Live catalog or governance synchronization to OpenMetadata or OpenLineage.
- Remote tracked-spec polling and authenticated source access.
- Runtime subscriptions, adapters, replay, and materialization.
- Distributed registry synchronization beyond the current file-first model.
- Hosted documentation.

## Development

```bash
cd cli
uv sync --extra dev --frozen
uv run pytest tests/ --tb=short
uv run modelable validate ../samples/mvp --strict
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete contributor workflow.

## Documentation

- [Documentation index](docs/README.md)
- [Language reference](docs/language-reference.md)
- [Tooling reference](docs/cli-reference.md)
- [Architecture and system specification](docs/architecture.md)
- [Getting started and migration](docs/getting-started.md)
- [Sample models](samples/README.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Project governance](GOVERNANCE.md)

## License

Licensed under the [Apache License 2.0](LICENSE).

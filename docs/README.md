# Modelable Documentation

This directory contains the system specifications, design documents, and implementation plans for the Modelable platform.

## Start here

- **[modelable-system-spec.md](modelable-system-spec.md)** — Product source of truth. Read this first for design principles, core concepts, type system, versioning, governance, and MVP scope.

## Specification index

| Document | What it covers | Depends on |
|---|---|---|
| [modelable-system-spec.md](modelable-system-spec.md) | Design principles, core concepts, type system, projections, streaming, runtime architecture, versioning, governance, lineage, MVP scope | — |
| [idl-design-spec.md](idl-design-spec.md) | `.mdl` IDL language design — syntax, types, projections, output targets, federation, LSP, LLM integration | modelable-system-spec.md, distributed-lineage-spec.md |
| [cli-spec.md](cli-spec.md) | CLI command reference — all `modelable` subcommands, exit codes, phased delivery | idl-design-spec.md, cli-tooling-spec.md |
| [distributed-lineage-spec.md](distributed-lineage-spec.md) | Federated registry network — git-based DAG, content signatures, consumer write-backs | idl-design-spec.md |
| [ownership-permissions-spec.md](ownership-permissions-spec.md) | Field-level and entity-level ownership, permissions, classification, redaction, audit | modelable-system-spec.md |
| [adapter-architecture-spec.md](adapter-architecture-spec.md) | Ports & Adapters architecture, CloudEvents envelope, adapter bindings, artifact outputs | modelable-system-spec.md |
| [external-tools-data-modelling.md](external-tools-data-modelling.md) | Boundary with external tools — JSON Schema, Apicurio, OpenMetadata, ODCS, phased incorporation | modelable-system-spec.md, adapter-architecture-spec.md |
| [platform-usage-scenarios-spec.md](platform-usage-scenarios-spec.md) | Phase 5 runtime deployment scenarios — warehouse, microservices, ML, compliance | external-tools-data-modelling.md |
| [technology-evaluation.md](technology-evaluation.md) | Phase 5 runtime technology evaluation — CDC, streaming, materialization backends | external-tools-data-modelling.md |
| [cli-tooling-spec.md](cli-tooling-spec.md) | Python development environment — uv, Hatchling, project layout, bootstrap script | cli-spec.md |
| [mvp-implementation-plan.md](mvp-implementation-plan.md) | Phase 1 MVP delivery plan — milestones, acceptance checks, verification policy | modelable-system-spec.md, cli-spec.md, emitter-spec.md |
| [idl-parser-implementation-plan.md](idl-parser-implementation-plan.md) | Step-by-step implementation guide for Phase 1 parser, IR, transformer, semantic validation, compiler | idl-design-spec.md, cli-tooling-spec.md |
| [data-model-languages.md](data-model-languages.md) | Research — evaluated DSLs and expression languages (Smithy, TypeSpec, LinkML, CEL, etc.) | — |
| [emitter-spec.md](emitter-spec.md) | Output target generation — JSON Schema, TypeScript, Avro, Protobuf, SQL DDL, AsyncAPI, Markdown | idl-design-spec.md, adapter-architecture-spec.md |
| [lsp-spec.md](lsp-spec.md) | Language Server Protocol — IDE support, diagnostics, autocomplete, federation-aware features | idl-design-spec.md, distributed-lineage-spec.md |
| [llm-integration-spec.md](llm-integration-spec.md) | AI-powered commands — `generate`, `describe`, `update`, `transform`, `suggest-projection`, `chat`; provider-backed local Ollama support | cli-spec.md, idl-design-spec.md |
| [cel-integration-spec.md](cel-integration-spec.md) | CEL expression language — embedding, validation, lineage extraction from computed fields | idl-design-spec.md, idl-parser-implementation-plan.md |
| [migration-guide.md](migration-guide.md) | Migrating from OpenAPI, JSON Schema, Protobuf, SQL DDL, Avro to Modelable | cli-spec.md, llm-integration-spec.md |
| [agent-governance.md](agent-governance.md) | Agent operating policy — local gate, test gates, PR handling, and CI expectations | AGENTS.md, modelable-system-spec.md |

## Phases at a glance

| Phase | Focus | Key documents |
|---|---|---|
| 1 | Local modelling compiler (parser, validate, compile, docs) | idl-parser-implementation-plan.md, cli-spec.md, cli-tooling-spec.md |
| 2 | Artifact registry integration (Apicurio) | external-tools-data-modelling.md §4 |
| 3 | Catalog / governance integration (OpenMetadata) | external-tools-data-modelling.md §5, ownership-permissions-spec.md |
| 4 | Contract interchange (ODCS) | external-tools-data-modelling.md §6 |
| 5 | Runtime deployment, streaming, materialization | platform-usage-scenarios-spec.md, technology-evaluation.md, adapter-architecture-spec.md |

## Sample scenarios

See [samples/scenarios](../samples/scenarios/) for worked examples. Each scenario maps to one or more specification sections.

The Phase 1 implementation plan uses a minimal `samples/mvp/` sample as the strict acceptance target. The richer `samples/scenarios/` examples are illustrative and may include future-phase constructs.

---

*For agent-specific conventions and build guidance, see the root [AGENTS.md](../AGENTS.md).*

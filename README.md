# Modellable

Modellable is a **meta-model framework** for defining, tracing, and governing domain-owned data models across disparate systems. It acts as a semantic layer on top of existing infrastructure to ensure maximum traceability and understandability of every data property.

## Documentation

All documentation is located in the [docs/](docs/) directory.

### Core Specifications
- [Modellable System Specification](docs/modellable-system-spec.md) — The product source of truth.
- [CLI Specification](docs/cli-spec.md) — Command-line interface design and reference.
- [Adapter Architecture](docs/adapter-architecture-spec.md) — How Modellable connects to disparate systems.
- [Ownership & Permissions](docs/ownership-permissions-spec.md) — Governance and access control model.

### Design & Research
- [Modellable IDL Design](docs/idl-design-spec.md) — Syntax and rationale for the `.mdl` language.
- [Data Model Languages](docs/data-model-languages.md) — Research on existing modeling languages.
- [Technology Evaluation](docs/technology-evaluation.md) — Evaluation of streaming and storage backends.
- [Platform Usage Scenarios](docs/platform-usage-scenarios-spec.md) — Common use cases and patterns.

### Current Implementation Plans
- [IDL Parser, IR, and Validation](docs/idl-parser-implementation-plan.md) — Phase 1 implementation plan.

## Project Structure

- `docs/`: Consolidated documentation, specifications, research, and plans.
- `samples/`: Worked `.mdl` scenario examples.
- `AGENTS.md`: Instructions for AI agents working on this repository.

## Getting Started

Modellable is currently in **Phase 1: Local modelling compiler**. See the [System Specification](docs/modellable-system-spec.md) for the roadmap and the [IDL Design](docs/idl-design-spec.md) for how to write models.


# Modelable

Modelable is a **meta-model framework** for defining, tracing, and governing domain-owned data models across disparate systems. It acts as a semantic layer on top of existing infrastructure to ensure maximum traceability and understandability of every data property.

## Documentation

All documentation is located in the [docs/](docs/) directory.

### Core Specifications
- [Modelable System Specification](docs/modelable-system-spec.md) — The product source of truth.
- [CLI Specification](docs/cli-spec.md) — Command-line interface design and reference.
- [Adapter Architecture](docs/adapter-architecture-spec.md) — How Modelable connects to disparate systems.
- [Ownership & Permissions](docs/ownership-permissions-spec.md) — Governance and access control model.

### Design & Research
- [Modelable IDL Design](docs/idl-design-spec.md) — Syntax and rationale for the `.mdl` language.
- [Data Model Languages](docs/data-model-languages.md) — Research on existing modeling languages.
- [Technology Evaluation](docs/technology-evaluation.md) — Evaluation of streaming and storage backends.
- [Platform Usage Scenarios](docs/platform-usage-scenarios-spec.md) — Common use cases and patterns.

### Current Implementation Plans
- [MVP Implementation Plan](docs/mvp-implementation-plan.md) — Phase 1 delivery sequence and acceptance checks.
- [IDL Parser, IR, and Validation](docs/idl-parser-implementation-plan.md) — Phase 1 implementation plan.
- [Agent Governance](docs/agent-governance.md) — Agent operating policy, test gates, PR handling, and local gate expectations.

## Project Structure

- `docs/`: Consolidated documentation, specifications, research, and plans.
- `samples/`: Worked `.mdl` examples. `samples/mvp/` is planned as the strict Phase 1 acceptance sample; `samples/scenarios/` contains broader illustrative scenarios.
- `AGENTS.md`: Instructions for AI agents working on this repository.

## Getting Started

### Install and run

```bash
cd cli
uv sync --extra dev
uv run modelable --help
```

### Working commands (Phase 1 current)

```bash
# Validate .mdl files
uv run modelable validate ../samples/mvp

# Compile to JSON Schema or Markdown docs
uv run modelable compile ../samples/mvp --target json-schema --out ../dist/jsonschema
uv run modelable compile ../samples/mvp --target markdown --out ../dist/docs

# Inspect auto-generated projections for a model
uv run modelable inspect customer.Customer@1 --auto --path ../samples/mvp

# Run tests
uv run pytest tests/ -v
```

### Milestone status

| Milestone | Goal | Status |
|---|---|---|
| 0 — Tooling baseline | CLI package, uv, CI | Complete |
| 1 — Parser + IR + validate | Parse `.mdl`, semantic validation | Complete |
| 2 — Registry graph + resolver | SQLite index, cross-file resolution | Complete (lineage edges deferred to M3) |
| 3 — Planner + auto projections | Auto-projection expansion, CEL, lineage | Complete — CEL validation, lineage extraction, plan docs done |
| 4 — Compatibility + governance | `diff`, breaking-change detection, PII governance | Not started |
| 5 — Emitters | JSON Schema, Markdown, TypeScript | Partial — JSON Schema + Markdown done; TypeScript remaining |
| 6 — CLI workflows | `resolve`, `lineage`, `diff`, `codegen`, `scenario` | Partial — `validate`, `compile`, `docs`, `inspect --auto` done |
| 7 — Hardening | Smoke tests, clean-checkout verification | Not started |

See [`docs/mvp-implementation-plan.md`](docs/mvp-implementation-plan.md) for detailed task checklists.


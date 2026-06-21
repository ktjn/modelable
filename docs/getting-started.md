# Getting Started and Migration Guide

Use this guide to install Modelable, validate a first workspace, consume its
artifacts from another project, or migrate an existing contract format.

## Quick Start

Modelable requires Python 3.14 or newer. Install the command-line tool with
`uv`:

```bash
uv tool install modelable
modelable --version
```

Inside a project, add it as a development dependency instead:

```bash
uv add --dev modelable
```

Create or copy a `.mdl` workspace, then run:

```bash
modelable validate ./models
modelable compile ./models --target json-schema --out ./dist/jsonschema
modelable docs ./models --out ./dist/docs
```

The VS Code extension starts `modelable lsp`. Ensure the command is available
on `PATH`, or configure the extension's Python path or server command.

Generated artifacts are consumer contracts, not the source of truth. Commit
`.mdl` definitions; regenerate schemas, language bindings, and Markdown in CI
unless a consumer workflow deliberately reviews generated output.

Before upgrading, read the root [changelog](../CHANGELOG.md) for language or
artifact compatibility notes.

> **Status:** Approved guidance for adopting Modelable from existing schema and contract formats.
>
> **Scope:** Practical migration paths from OpenAPI, JSON Schema, Protobuf, SQL DDL, Avro, and existing internal DSLs into `.mdl`.

## 1. Migration Purpose

This guide helps teams introduce Modelable without rewriting every system at once. Migration should start with domain-owned canonical models, then add projections and adapter bindings around existing infrastructure.

The goal is not to mirror every existing table, topic, or API one-for-one. The goal is to identify the canonical domain contracts and make downstream derivation explicit.

## 2. Migration Principles

1. Start with the owning domain, not the consuming system.
2. Model canonical entities and events before projections.
3. Preserve published contracts as immutable versions.
4. Treat incompatible historical changes as new versions.
5. Keep adapter-specific details in bindings, not model definitions.
6. Preserve or add PII, classification, ownership, and deprecation metadata.
7. Validate after each migrated domain before adding cross-domain projections.

## 3. Source Format Mapping

| Source | Primary Mapping | Notes |
|---|---|---|
| OpenAPI 3.x | Request/response schemas become projections; shared schemas may become entities or value objects | Avoid treating public API shape as canonical unless that API is owned by the domain |
| JSON Schema | Object schemas become `entity`, `event`, or `value` models | Add keys and ownership explicitly |
| Protobuf | Messages become models; services imply projections or API targets | Preserve field numbers in metadata if needed |
| SQL DDL | Tables become candidate entities; views become candidate projections | Move table/index/storage details to bindings |
| Avro | Records often become event models | Preserve logical types and namespace metadata |
| dbt `schema.yml` / `manifest.json` | Models and source tables become draft entities for review | Preserve group/access/ownership metadata manually when dbt metadata is incomplete |
| FHIR R4 `StructureDefinition` | Direct child elements become draft model fields; repeating elements become arrays; simple extension slices use their nested `value[x]` type | Complex FHIR element types may need manual value-model refinement |
| ODCS YAML | Contract schema objects become draft entities | Review ownership, classification, and required-field semantics |
| Existing YAML/DSL | Rewrite to `.mdl` with `modelable generate` assistance | Review all generated lineage and governance annotations |

## 4. Step-by-Step Workflow

### Step 1: Inventory

Create a list of source artifacts:

```text
source system
owning team
artifact path
artifact kind
current version
contains PII/restricted data
known consumers
```

### Step 2: Choose Domain Boundaries

Map each artifact to an owning domain. If ownership is unclear, pause migration for that artifact. Modelable requires domain-owned canonical models.

### Step 3: Extract Canonical Models

For each domain, create the smallest useful set of canonical models:

```mdl
domain customer {
  owner: "customer-platform"
  description: "Customer identity and lifecycle."

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @pii email?:     string
    status:          enum(active, suspended, deleted)
    createdAt:       timestamp
  }
}
```

### Step 4: Add Projections for Existing Consumers

Map existing views, API responses, topics, or files to projections:

```mdl
domain billing {
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    billingCustomerId <- c.customerId
    @pii invoiceEmail <- c.email
    isActive          = c.status == "active"
  }
}
```

### Step 5: Add Bindings Separately

Keep storage and transport details outside canonical models:

```mdl
binding customer-postgres {
  model:   customer.Customer @ 1
  adapter: postgres
  table:   "customers"
}
```

### Step 6: Validate and Diff

Run:

```bash
modelable validate ./models
modelable lineage billing.BillingCustomer@1 --path ./models
modelable diff customer.Customer@1 customer.Customer@2 --path ./models
```

## 5. Format-Specific Guidance

### 5.1 OpenAPI

- Treat path operations as API surface, not source truth.
- Convert request bodies to `request` projections.
- Convert response bodies to `reply` projections.
- Convert shared component schemas to value objects only when they are embedded and not independently owned.
- Preserve operation-level security as projection or binding access policy metadata.

### 5.2 JSON Schema

- Use `required` to determine optionality.
- Convert `format: uuid`, `date`, `date-time`, and binary encodings to Modelable scalar types.
- Convert `$ref` to named value objects or `ref<Domain.Model>` depending on ownership.
- Add `@classification` manually when source schemas lack governance metadata.

### 5.3 Protobuf

- Map packages to candidate domains only when package ownership matches domain ownership.
- Preserve message names as model names where possible.
- Map `repeated T` to `array<T>`.
- Map `oneof` to an enum discriminator plus optional fields until union types are explicitly supported.
- Preserve field numbers in metadata for downstream emitters.

### 5.4 SQL DDL

- Tables with primary keys usually become entities.
- Append-only audit tables usually become events.
- Lookup tables may become value objects or enums.
- Views should become projections.
- Foreign keys become `ref<Domain.Model>` only when they represent domain references, not merely storage joins.
- Indexes, partitions, engines, and tablespaces belong in bindings.

### 5.5 Avro

- Avro records used on topics usually become event models.
- Avro logical types map to Modelable scalar types.
- Union with `null` maps to optional fields.
- Registry subject names should be preserved as metadata or binding configuration, not canonical model names unless they match domain language.

## 6. AI-Assisted Migration

Use `modelable generate` to draft `.mdl`, then review the output:

```bash
modelable generate --from ./openapi.yaml --output ./models/customer-api.mdl
modelable generate --from ./dbt/schema.yml --domain customer --output ./models/customer.mdl
modelable generate --from ./dbt/schema.yml --name customers --domain customer --output ./models/customer-source.mdl
modelable generate --from ./fhir/PatientProfile.json --domain clinical --output ./models/patient.mdl
modelable generate --from ./contracts/customer.yml --domain customer --output ./models/customer-contract.mdl
modelable validate ./models/customer-api.mdl
```

Review checklist:

- Does each model have a clear owning domain?
- Are keys explicit?
- Are versions and change kinds correct?
- Are PII and restricted fields annotated?
- Are API-specific shapes represented as projections rather than canonical models?
- Are adapter details kept in bindings?

## 7. Common Gaps

| Gap | Resolution |
|---|---|
| No owner for a schema | Do not publish until ownership is assigned |
| No stable key | Use an event or value model, or add a domain-approved identity |
| API response treated as canonical model | Split into source entity and response projection |
| Storage column names in model fields | Move physical names to bindings |
| Missing PII classification | Add annotations before publishing |
| Historical breaking change hidden in one version | Create separate model versions with `changeKind: breaking` |

## 8. Acceptance Criteria

- Migrated canonical models have owners, keys where applicable, versions, and change kinds.
- Consumer-specific shapes are represented as projections with explicit lineage.
- Existing adapter details are represented in bindings.
- `modelable validate` succeeds for the migrated workspace.
- Generated JSON Schema and TypeScript artifacts preserve model version metadata.
- Governance annotations are present for PII, restricted, and confidential fields.

## 9. Dependencies

- [Tooling reference](cli-reference.md) for `generate`, `validate`, `lineage`,
  `diff`, LSP, and AI-assisted authoring behavior.
- [Language reference](language-reference.md) for ownership, access metadata,
  annotations, and `.mdl` syntax.
- [Architecture](architecture.md) for canonical-model and adapter boundaries.

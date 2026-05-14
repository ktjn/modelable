# Modellable System Specification

## 1. Purpose

Modellable is a **meta-model framework** for defining, tracing, and governing domain-owned data models across disparate systems. It acts as a semantic layer on top of existing infrastructure (databases, APIs, message brokers) to ensure maximum traceability and understandability of every single data property.

The framework ensures that any property—whether it appears in a database table, an API response, or a streaming event—can be traced back to the specific domain and canonical model that owns it.

Modellable provides:

- **Universal Lineage:** Tracking the origin and transformation of every field across system boundaries.
- **Domain-Owned Contracts:** Explicit ownership and lifecycle for canonical models.
- **Explicit Mapping:** A declarative way to project, subset, and join models while maintaining property-level "back-references."
- **Platform-Agnostic Governance:** Applying policies (PII, security, retention) at the source and propagating them to all consumers.

Modellable is not a database; it is the **lineage backbone** that makes data movement and consumption predictable and auditable.

## 2. Design Principles

### 2.1 Domain Ownership

Each model is owned by exactly one domain. The owning domain controls the canonical definition, lifecycle, versioning, access policy, and deprecation policy for that model.

Other domains may consume source models only through explicitly declared projections or subscriptions.

### 2.2 Property-Level Traceability

Every single property in the system must be traceable. If a field exists in a consumer's projection, the framework must be able to answer:
- Which source model and field did this come from?
- Who owns that source model?
- What transformations (if any) were applied?
- What are the governance constraints (e.g., PII) inherited from the source?

### 2.3 Immutable Contracts

Published model versions and projection versions are immutable. Any incompatible change must create a new version.

Mutable drafts may exist before publication, but published contracts must be stable so downstream systems can rely on them.

### 2.4 Platform-Neutral Definitions

Model and projection definitions must not depend on a specific database or streaming platform.

Database and stream integrations are expressed through adapter bindings. The same logical model should be usable with PostgreSQL, MongoDB, Kafka, Pulsar, NATS, or other supported systems when the adapter capabilities are sufficient.

### 2.5 Explicit Derivation

All derived data must be declared. Field renames, type conversions, computed fields, filters, joins, aggregations, and materialized replicas must be traceable back to their source models and source fields.

### 2.6 Framework-First Integration

Modellable is designed to wrap existing systems. It should not require a "rip and replace" of current infrastructure, but rather provide the mapping layer that makes existing data "modellable" and traceable.

### 2.7 Compatibility Before Runtime

The system should reject invalid or incompatible definitions before runtime when possible. Runtime failures should be reserved for operational issues such as unavailable streams, write conflicts, bad source payloads, or adapter outages.

## 3. Core Concepts

### 3.1 Domain

A domain is an ownership boundary for models and projections.

Required properties:

- `name`: Unique domain identifier.
- `owner`: Team, service, or organization responsible for the domain.
- `description`: Human-readable purpose.
- `policies`: Optional governance, privacy, and access defaults.

Example:

```mdl
domain customer {
  owner: "customer-platform"
  description: "Customer identity and lifecycle data."
}
```

### 3.2 Model

A model is a canonical business entity, event, value object, or aggregate owned by a domain.

Required properties:

- `domain`: Owning domain.
- `name`: Unique model name within the domain.
- `kind`: `entity`, `event`, `value_object`, or `aggregate`.
- `identity`: Key definition for addressable records when applicable. The `key` field accepts either a single field name (string) or an ordered list of field names for composite keys.
- `versions`: Published model versions.

Example:

```mdl
domain customer {
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
```

### 3.3 Model Version

A model version is an immutable schema and semantic contract for a model.

Required properties:

- `version`: Integer version number. Must be greater than the previous published version for the same model.
- `changeKind`: `additive` or `breaking`. Required when `status` is `published`. Omit for `draft`. See section 8.1 for enforcement rules.
- `status`: `draft`, `published`, `deprecated`, or `retired`.
- `fields`: Field definitions.
- `identity`: Identity fields for entities and aggregates.
- `constraints`: Optional validation constraints.
- `metadata`: Optional classification, documentation, and ownership metadata.

Example:

```mdl
domain customer {
  entity Customer @ 2 (additive) {
    @key        customerId: uuid
                legalName:  string
    @pii        email?:     string
                status:     enum(active, blocked, deleted)
                createdAt:  timestamp
  }
}
```

Composite key example:

```mdl
domain orders {
  entity OrderLineItem @ 1 (additive) {
    @key orderId:    uuid
    @key lineItemId: uuid
    sku:             string
    quantity:        int
  }
}
```

### 3.4 Projection

A projection is a versioned derived contract based on one or more source model versions.

Projections may be used for:

- Consumer-specific contracts.
- Read models.
- API response models.
- Stream output contracts.
- Materialized database replicas.
- Analytics-ready datasets.
- Aggregated views.

Required properties:

- `domain`: Domain that owns the projection.
- `name`: Projection name.
- `version`: Projection version.
- `sources`: Source model versions with optional joins and filters.
- `identity`: Target identity, if materializable.
- `fields`: Target fields and derivation rules (map-based).
- `materialisation`: Optional strategy for persistence (strategy, key, partitionBy, binding, etc.).
- `subscription`: Optional stream/change source configuration (source, adapter, fromOffset, filter, etc.).

Example:

```mdl
domain billing {
  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
  {
    billingCustomerId <- c.customerId
    name             <- c.legalName
    @pii invoiceEmail <- c.email
    isBillable        = c.status == "active"
  }
}
```

### 3.5 Subscription

A subscription declares how a projection is kept up to date from one or more source streams or change sources.

Required properties:

- `name`: Unique subscription name.
- `projection`: Target projection version.
- `source`: Stream, change data capture source, or model source.
- `target`: Stream or database target.
- `delivery`: Delivery and retry semantics.
- `state`: Optional state management for joins and aggregations.

Example (Phase 5 — subscription IDL syntax is defined in the Phase 5 spec):

```mdl
subscription billing-customer-replica {
  projection: billing.BillingCustomer @ 1

  source {
    type: stream
    model: customer.Customer @ 2
  }

  target {
    type: database
    adapter: postgres
    table: "billing_customers"
  }

  delivery {
    mode: at_least_once
    idempotencyKey: billingCustomerId
    deadLetter: "billing-customer-replica-dlq"
  }
}
```

### 3.6 Adapter Binding

An adapter binding connects a logical model, projection, subscription, or materialization to a concrete backend.

Adapter bindings must be separate from model definitions.

Example:

```mdl
binding customer-postgres {
  model:   customer.Customer @ 2
  adapter: postgres
  table:   "customers"
  fields: {
    customerId -> customer_id
    legalName  -> legal_name
    createdAt  -> created_at
  }
}
```

## 4. Type System

The core type system must support:

| IDL type | Description |
|:---------|:------------|
| `string` | UTF-8 string |
| `bool` | Boolean |
| `int` | 64-bit integer |
| `float` | 64-bit float |
| `decimal(p,s)` | Arbitrary-precision decimal |
| `uuid` | UUID v4 |
| `timestamp` | UTC datetime with microsecond precision |
| `date` | Calendar date (no time component) |
| `time` | Time of day (no date component) |
| `duration` | ISO 8601 duration |
| `binary` | Raw bytes |
| `enum(a, b, c)` | Inline enumeration |
| `array<T>` | Ordered list of type T |
| `map<K, V>` | Key-value map |
| `ref<Domain.Model>` | Cross-domain model reference |
| Named type (bare `IDENT`) | Reference to a `value` object in the same domain |

Field modifiers:

- `?` suffix — optional field (nullable / not required)
- `@key` — identity field (required for `entity` and `aggregate` models)
- `@pii` — marks field as personally identifiable information
- `@classification("level")` — governance classification (`public`, `internal`, `confidential`, `restricted`)
- `@deprecated(replacedBy: "fieldName")` — marks field as deprecated
- `@owner("team")` — field-level ownership override

Example:

```mdl
@pii
@classification("confidential")
email?: string
```

## 5. Projection Semantics

### 5.1 Field Selection

A projection may expose a subset of source fields. The `<-` operator declares a direct mapping and makes lineage unambiguous.

```mdl
customerId <- c.customerId
name       <- c.legalName
```

### 5.2 Field Rename

Renames are expressed as projection mappings with a different target name on the left.

```mdl
invoiceEmail <- c.email
```

### 5.3 Computed Fields

Computed fields use the `=` operator with a CEL expression over source fields. The compiler records which source fields appear in the expression for lineage tracking.

```mdl
isActive = c.status == "active"
```

The expression language must be deterministic, side-effect free, and validateable by the planner.

### 5.4 Filters

Row-level filters are expressed as `join` conditions or as boolean computed fields. A dedicated `where` clause may be added in a future version.

### 5.5 Joins

A projection may join multiple source models. The `on` expression is a CEL equality comparison between aliased fields.

```mdl
projection OrderWithCustomer @ 1
  from orders.Order @ 3 as o
  join customer.Customer @ 2 as c on o.customerId == c.customerId
{
  orderId      <- o.orderId
  customerName <- c.legalName
  total        <- o.totalAmount
}
```

The planner must reject joins that cannot be executed by the selected runtime or adapters.

### 5.6 Aggregations

Aggregations use `group by` on the source alias and aggregate functions (`count`, `sum`, `min`, `max`, `avg`) in computed fields.

```mdl
domain analytics {
  projection CustomerOrderSummary @ 1
    from orders.Order @ 3 as o
    group by o.customerId
  {
    customerId    <- o.customerId
    totalOrders    = count(o.orderId)
    lifetimeValue  = sum(o.totalAmount)
    lastOrderAt    = max(o.createdAt)
  }
}
```

Supported initial aggregate functions:

- `count`
- `sum`
- `min`
- `max`
- `avg`

Windowed aggregations may be added later.

## 6. Streaming Semantics

### 6.1 Change Event Envelope

Streaming model data must use a stable envelope.

```json
{
  "domain": "customer",
  "model": "Customer",
  "version": 2,
  "operation": "upsert",
  "key": "cust_123",
  "sequence": "00000000042",
  "timestamp": "2026-05-12T10:00:00Z",
  "payload": {
    "customerId": "cust_123",
    "legalName": "Acme AB",
    "email": "billing@acme.test",
    "status": "active",
    "createdAt": "2026-05-12T09:55:00Z"
  }
}
```

Required envelope fields:

- `domain`
- `model`
- `version`
- `operation`
- `key`
- `timestamp`
- `payload`

Recommended envelope fields:

- `sequence`
- `traceId`
- `correlationId`
- `producer`
- `schemaId`
- `sourceOffset`

Supported operations:

- `insert`
- `update`
- `upsert`
- `delete`
- `snapshot`

### 6.2 Delivery Modes

The platform must support:

- `at_most_once`
- `at_least_once`
- `effectively_once`

`effectively_once` means the runtime provides idempotent writes and deterministic replay, not that the underlying broker necessarily provides global exactly-once delivery.

### 6.3 Ordering

Ordering is guaranteed per model identity key when the selected stream adapter supports partitioning by key.

The system must not promise global ordering across all records or all domains.

### 6.4 Replay and Backfill

Subscriptions must support replay where the source adapter supports retained events or change logs.

Materialized projections must support rebuild from:

- Source streams.
- Source database snapshots.
- A combination of snapshot plus stream catch-up.

### 6.5 Dead Letter Handling

Invalid or unprocessable events must be routed to a dead-letter target when configured.

Dead-letter records should include:

- Original event.
- Validation error.
- Projection name and version.
- Subscription name.
- Processing timestamp.
- Retry count.

## 7. Runtime Architecture

### 7.1 Model Registry

The model registry stores:

- Domains.
- Models.
- Model versions.
- Projections.
- Projection versions.
- Subscriptions.
- Adapter bindings.
- Compatibility reports.
- Lineage metadata.
- Access policies.

The registry must expose APIs for:

- Create draft model.
- Publish model version.
- Deprecate model version.
- Register projection.
- Validate projection.
- Query lineage.
- Query compatibility.
- Export schemas and generated artifacts.

### 7.2 Compiler and Planner

The compiler normalizes definitions into an internal representation.

The planner validates whether a model, projection, or subscription can be executed against the selected adapters.

Planner responsibilities:

- Resolve source references.
- Validate field mappings.
- Validate expression types.
- Validate access permissions.
- Validate adapter capabilities.
- Determine whether execution is pushdown, runtime-based, or unsupported.
- Produce executable projection plans.

The planner's primary output is a **plan document** — a structured, serialisable artifact (JSON) that the runtime engine (Phase 5) interprets at execution time. Plan documents are not generated executable code; they are data that describes how to execute a projection. They are human-readable, diffable in git, and inspectable for debugging.

A plan document contains:

- Resolved source model versions (exact version numbers, not ranges).
- Field mapping table: each target field mapped to its source field and optional transformation expression.
- Filter expression in CEL string form.
- Join descriptors: type (`left`, `inner`), left key, right key, and declared cardinality.
- Aggregation descriptors: group-by fields and aggregate function per output field.
- Adapter capability assertions evaluated during planning.
- Planner metadata: validation timestamp and planner version.

Plan documents are written to `.modellable/plans/<domain>.<Projection>.v<version>.plan.json` by the `compile` command.

### 7.3 Runtime Engine

The runtime engine executes plans produced by the planner.

Execution modes:

- `batch`: Run projection over bounded data.
- `query`: Resolve projection on demand.
- `stream`: Transform events continuously.
- `materialized`: Maintain projected replica in target storage.

### 7.4 Materializer

The materializer keeps a target projection synchronized with source data.

It must support:

- Idempotent writes.
- Offset tracking.
- Retry policy.
- Dead-letter routing.
- Rebuild.
- Snapshot plus stream catch-up.
- Health and lag reporting.

### 7.5 Adapter Layer

Adapters isolate backend-specific behavior.

Adapter categories:

- Storage adapters.
- Stream adapters.
- Schema adapters.
- CDC adapters.

Each adapter must publish its capabilities so the planner can determine support.

Adapter capabilities are declared internally by each adapter implementation and are not authored in `.mdl` files. The planner queries adapter capability metadata at plan time. Example capability shape (internal representation):

```json
{
  "adapter": "postgres",
  "capabilities": {
    "storage": true,
    "transactions": true,
    "joins": true,
    "aggregations": true,
    "jsonFields": true,
    "cdc": "logical_decoding"
  }
}
```

## 8. Versioning and Compatibility

### 8.1 Model Versioning

Model versions are immutable once published.

Compatible changes:

- Add optional field.
- Add field with default.
- Add documentation.
- Add metadata.
- Mark field as deprecated.

Potentially incompatible changes:

- Add required field.
- Remove field.
- Rename field.
- Change field type.
- Change enum semantics.
- Change identity.
- Change nullability from nullable to non-nullable.
- Change validation constraints in a stricter way.

### 8.1.1 `changeKind` Declaration and Enforcement

When publishing a new model version (`status: published`), authors must declare `changeKind`:

- `additive` — only backward-compatible changes were made. The set of compatible changes is defined in section 8.1 above. Existing projections that pin an earlier version or use a compatible version range remain valid without re-publication.
- `breaking` — at least one incompatible change was made. The set of potentially incompatible changes is defined in section 8.1 above.

**Planner enforcement for `breaking` versions:**

When a new version with `changeKind: breaking` is published, the planner marks all projections that reference any version of that model as requiring re-validation. Subscriptions backed by an affected projection are blocked from planning until the projection author explicitly re-publishes a new projection version that references a valid source version. The registry must expose a `listAffectedProjections(domain, model, breakingVersion)` query to support this workflow.

**Planner enforcement for `additive` versions:**

Projections with exact version pins are unaffected. Projections using version ranges are automatically re-validated against the new version (see section 8.2). If re-validation passes, no author action is required.

**Draft versions:** `changeKind` is not required and is ignored for `draft` status versions.

### 8.2 Projection Versioning

Projection versions are immutable once published.

A projection version must declare exact source model versions unless explicitly configured to accept a compatible version range.

Example:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ >=2 <3 as c
{
  ...
}
```

**Version range resolution rules:**

- Ranges are resolved to the **highest published version** that satisfies the constraint at plan time.
- Since model versions are integers, range syntax uses integer comparisons: `>=2 <3` means "version 2 only", `>=2` means "version 2 or higher".
- Exact version pins (`version: 2`) are resolved immediately and are not affected by future publications. They are recommended for production projections that require maximum stability.
- When a new compatible (`changeKind: additive`) version is published within the declared range, the planner **automatically re-validates** the projection against the new resolved version. If re-validation passes, no projection author action is required.
- When a new version with `changeKind: breaking` is published and falls within the declared range, the planner raises a validation error and blocks the subscription. The projection author must update the version range and re-publish.
- The resolved concrete version is recorded in the plan document (see section 7.2). Re-planning uses the latest resolved version, not the version that was resolved at the last plan time.

### 8.3 Deprecation

Deprecation must be explicit and traceable.

```mdl
@deprecated(replacedBy: "primaryEmail")
email?: string
```

The `removalAfter` date is tracked in registry metadata outside the IDL field declaration.

The registry must be able to list consumers affected by a planned deprecation.

## 9. Governance and Access Control

The platform must support field-level classification.

Example classifications:

- `public`
- `internal`
- `confidential`
- `pii`
- `sensitive`
- `restricted`

Access checks must apply when:

- Creating projections.
- Creating subscriptions.
- Exporting schemas.
- Materializing projections.
- Reading registry metadata where sensitive fields are exposed.

The planner must reject projections that expose unauthorized fields.

## 10. Lineage

The registry must store lineage from target fields back to source fields.

Example lineage:

```text
billing.BillingCustomer.v1.invoiceEmail
  <- customer.Customer.v2.email
```

The system must answer:

- Which models depend on this source model?
- Which projections use this field?
- Which subscriptions materialize this projection?
- Which downstream systems are affected by a breaking change?
- Which fields contain data derived from PII?

## 11. Generated Artifacts

The system generates artifacts from the normalized model graph. External tools consume these artifacts; they do not feed back into the internal model.

```
Modellable IDL (.mdl files)
   |
   v
Lark Parser + Semantic Validator
   |
   v
Normalized Model Graph (Pydantic IR)
   |
   |-- JSON Schema
   |-- Markdown docs
   |-- TypeScript types
   |-- OpenMetadata metadata
   |-- ODCS export
   `-- Registry artifacts (Apicurio)
```

### Incorporation Order

Artifacts are introduced in phases. Later phases depend on the normalized graph being stable.

**Phase 1 — Local modelling compiler:**

- JSON Schema 2020-12 (first generated contract format)
- Markdown documentation
- TypeScript types (via `json-schema-to-typescript`)

**Phase 2 — Artifact registry:**

- Apicurio Registry (stores and versions generated schemas)

**Phase 3 — Catalog / governance sync:**

- OpenMetadata export (domains, assets, lineage, classification tags)

**Phase 4 — Contract interchange:**

- Open Data Contract Standard (ODCS) export
- Data Contract CLI compatibility

**Phase 5 — Event and API targets:**

- Avro (event schemas, Kafka contracts)
- Protobuf + Buf (gRPC, binary wire format)
- OpenAPI (REST API contracts)
- AsyncAPI (event contract documentation)

### External Tool Boundaries

| External Tool | Role | What Modellable Does Not Delegate |
| :--- | :--- | :--- |
| JSON Schema / jsonschema | Generated contract format and validation | Internal DSL definition |
| Apicurio Registry | Artifact storage and versioning | Source of truth |
| OpenMetadata | Catalog UI, ownership, lineage visualization | Projection resolution |
| ODCS / Data Contract CLI | Interchange and CI validation | Internal model shape |
| json-schema-to-typescript | TypeScript type generation | Custom TS generator |

### JSON Schema Extensions

Generated JSON Schema documents use `x-modellable-*` vendor extensions to carry Modellable-specific metadata:

| Extension | Purpose |
| :--- | :--- |
| `x-modellable` | Model kind, domain, name, and version block |
| `x-modellable-field` | Fully qualified field reference for lineage |
| `x-modellable-classification` | Field classification (pii, internal, confidential, etc.) |
| `x-modellable-lineage` | Source field reference for derived fields |
| `x-modellable-ref` | Cross-model reference |
| `x-modellable-por` | Portable ownership record reference |

All generated artifacts must include model version metadata.

## 12. Storage Model for Registry

The registry uses a **file-first, SQLite-indexed** storage model.

**Source of truth: `.mdl` files on disk.** Authors write and version-control `.mdl` definition files using the Modellable IDL. The registry never modifies these files. All definitions live in source control alongside application code.

**Derived index: SQLite.** The `modellable compile` command reads all `.mdl` files and writes a derived `registry.db` (SQLite) file to the `.modellable/` output directory. The database is a build artifact — never edited directly. Deleting it and re-running `compile` must produce an identical result.

SQLite is used because it provides efficient relational queries for lineage traversal, consumer lookup, and compatibility checks without requiring a server or any setup for local use.

**Output layout (post-compile, local mode):**

```
.modellable/
  registry.db                          # derived — rebuilt by `modellable compile`
  plans/
    customer.Customer.v2.plan.json     # interpreted plan document
  artifacts/
    customer/
      Customer.v2.json                 # generated JSON Schema
      Customer.v2.md                   # generated Markdown
      Customer.v2.ts                   # generated TypeScript types
```

**Minimum logical entities in `registry.db`:**

- `domains`
- `models`
- `model_versions`
- `fields`
- `projections`
- `projection_versions`
- `projection_sources`
- `projection_fields`
- `field_mappings`
- `aggregations`
- `subscriptions`
- `adapter_bindings`
- `compatibility_reports`
- `lineage_edges`
- `access_policies`

Published definitions are stored as complete immutable `.mdl` documents within the source files to preserve exact historical contracts. The SQLite index is derived from these documents, not the other way around.

### 12.1 Distributed Mode

When a `registry` block is present in `workspace.mdl`, the compiler operates in **distributed mode**. Two additional SQLite files and an append-only event log directory are created:

```
.modellable/
  registry.db                          # owned domains — derived from .mdl files
  mirror.db                            # read-only foreign model replicas
  lineage.db                           # lineage index — derived from lineage-log/
  lineage-log/
    2026-05-14.ndjson                  # append-only lineage events (source of truth)
  plans/
    billing.BillingCustomer.v1.plan.json
  artifacts/
    billing/
      BillingCustomer.v1.json
      BillingCustomer.v1.ts
      BillingCustomer.v1.md
```

The `lineage-log/` directory is the only artifact that must be committed to source control or backed up. All SQLite files are derived from `.mdl` source files plus the event log.

Every published model version receives a **content signature** — a SHA-256 hash of the canonical model definition. The signature is stored on `model_versions` and included in cross-registry lineage edges, enabling tamper-evident, offline-verifiable lineage chains.

See [distributed-lineage-spec.md](distributed-lineage-spec.md) for the full design: federation topology, event types, Merkle hash chain, peer sync modes, failure modes, and migration path.

## 13. APIs

### 13.1 Registry API

Required operations:

- `createDomain`
- `createModelDraft`
- `publishModelVersion`
- `deprecateModelVersion`
- `createProjectionDraft`
- `publishProjectionVersion`
- `validateProjection`
- `getModelVersion`
- `getProjectionVersion`
- `listDependencies`
- `listConsumers`
- `checkCompatibility`
- `exportArtifact`

### 13.2 Runtime API

Required operations:

- `planProjection`
- `runBatchProjection`
- `startSubscription`
- `stopSubscription`
- `rebuildMaterialization`
- `getSubscriptionStatus`
- `getProcessingErrors`
- `retryDeadLetter`

## 14. Error Handling

### 14.1 Definition Errors

Definition errors must prevent publication.

Examples:

- Unknown source model.
- Unknown source field.
- Type mismatch.
- Invalid expression.
- Unsupported aggregation.
- Unauthorized field access.
- Adapter capability mismatch.

### 14.2 Runtime Errors

Runtime errors must be observable and recoverable where possible.

Examples:

- Source stream unavailable.
- Target database unavailable.
- Invalid source payload.
- Write conflict.
- Offset commit failure.
- Dead-letter write failure.

Runtime errors must include enough context to identify:

- Subscription.
- Projection.
- Source event.
- Target operation.
- Error category.
- Retry state.

## 15. Observability

The system must expose:

- Subscription health.
- Processing lag.
- Last processed offset.
- Throughput.
- Error count.
- Dead-letter count.
- Rebuild progress.
- Adapter health.
- Projection version currently deployed.

Logs and metrics must include:

- Domain.
- Model.
- Model version.
- Projection.
- Projection version.
- Subscription.

## 16. Security Requirements

The system must support:

- Authentication for registry and runtime APIs.
- Authorization at domain, model, projection, and field level.
- Audit logs for publication, deprecation, access policy changes, and subscription changes.
- Optional encryption metadata for sensitive fields.
- Redaction rules for logs and dead-letter payloads.

PII and restricted fields must not be exposed to projections unless explicitly permitted.

## 17. MVP Scope (Phase 1)

The first version implements the local modelling compiler. Runtime materialization and external registry integrations are deferred.

### 17.1 Implementation Stack

- **Parser:** `lark>=1.1` (Earley parser, EBNF grammar in `cli/src/modellable/grammar/modellable.lark`).
- **IR:** `pydantic>=2.0` (typed internal model graph; not exposed as the external contract format).
- **Output validation:** `jsonschema>=4.23`, `referencing>=0.35`.
- **Output:** JSON Schema 2020-12, Markdown, TypeScript (via `json-schema-to-typescript`).
- **CLI:** `click>=8.1`, `rich>=13.0`, `anthropic>=0.40`.

### 17.2 CLI Commands

See the [Modellable CLI Specification](cli-spec.md) for the full command reference.

### 17.3 Included in MVP

- Domain registry.
- Model definition and immutable publishing.
- Projection definition with field selection, rename, simple expressions (CEL), and filters.
- Exact source version references.
- Compatibility checks for additive and breaking changes.
- Lineage tracking.
- JSON Schema 2020-12 generation with `x-modellable-*` extensions.
- TypeScript type generation via `json-schema-to-typescript`.
- Markdown documentation generation.
- Basic CLI for publishing, validating, compiling, and exporting definitions.

### Deferred

- PostgreSQL storage adapter (Phase 5).
- Kafka stream adapter (Phase 5).
- Materialized projection into PostgreSQL (Phase 5).
- Apicurio Registry integration (Phase 2).
- OpenMetadata integration (Phase 3).
- ODCS / Data Contract CLI integration (Phase 4).
- Avro, Protobuf, OpenAPI, AsyncAPI generation (Phase 5).
- Multi-source joins.
- Stateful aggregations.
- Windowed aggregations.
- Multiple stream backends.
- Multiple database backends.
- Advanced policy engine.
- Visual modeling UI.
- Automatic migration generation.
- Kafka runtime provisioning, Redis materialisers, ClickHouse loaders, Feast, API gateways, dbt, Great Expectations, Soda.
- Distributed registry peer server (registry API endpoint, mTLS, peer sync HTTP handlers) — Phase 2.
- Lineage event streaming to Kafka / NATS JetStream — Phase 5.
- Transparency log integration for checkpoint hash publication — Phase 3.

## 18. Non-Goals

The platform is not initially:

- A replacement for all database schema migration tools.
- A universal query engine.
- A complete data catalog.
- A full data warehouse transformation platform.
- A generic ETL tool.
- A business intelligence semantic layer.

It may integrate with those systems, but its primary responsibility is versioned domain model contracts and derived projections.

## 19. Open Design Decisions

All design decisions have been resolved.

**Resolved:**

- **Definition IDL:** Custom text IDL (`.mdl` files), parsed with Lark (Earley grammar). See [idl-design-spec.md](idl-design-spec.md) for the full design rationale and syntax reference.
- **Expression language for computed fields:** CEL (Common Expression Language). Deterministic, non-Turing-complete, sandboxable.
- **Internal parser models:** `pydantic`. Not exposed as the external contract format.
- **First generated artifact:** JSON Schema 2020-12.
- **TypeScript generation:** Delegated to `json-schema-to-typescript`. No custom generator.
- **Version scheme:** Integer versions with a required `changeKind: additive | breaking` declaration on publish. See section 8.1.
- **Composite keys:** Supported in MVP. `identity.key` accepts a string (single field) or a list (composite). See section 3.3.
- **Version ranges in projections:** Allowed in MVP. The planner resolves to the highest satisfying published version at plan time. See section 8.2.
- **Registry storage:** File-first (`.mdl` source of truth) with a SQLite derived index written by `compile`. In distributed mode a `lineage-log/` NDJSON append-only log is the source of truth for cross-registry lineage, and `lineage.db` is derived from it. See section 12 and [distributed-lineage-spec.md](distributed-lineage-spec.md).
- **Runtime plan execution:** Interpreted plan documents (structured JSON artifacts). Not generated code. See section 7.2.

## 20. Acceptance Criteria

The system is acceptable when:

- A domain can publish a model version.
- Another domain can define and publish a projection over that model.
- The system can validate the projection before runtime.
- The system can detect whether a model change breaks existing projections.
- The system can show lineage from projection fields to source fields.
- A subscription can stream source changes into a materialized projected PostgreSQL table.
- The materialization can be replayed or rebuilt.
- The model and projection can be exported as JSON Schema and TypeScript types.
- Unauthorized projection of restricted fields is rejected.




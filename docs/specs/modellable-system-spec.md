# Modellable System Specification

## 1. Purpose

Modellable is a platform for defining domain-owned data models and using those models across systems through versioned projections, subsets, aggregations, and streaming replicas.

The system must let each domain define its own canonical models while allowing other domains and systems to consume derived contracts without directly coupling to the source database or internal implementation.

The platform must support:

- Domain-owned canonical data models.
- Immutable model versions.
- Projections that select, rename, transform, join, and aggregate data.
- Cross-domain model dependencies.
- Versioned consumer-facing contracts.
- Streaming data between systems.
- Materialized projected replicas.
- Multiple database backends.
- Multiple streaming platforms.
- Compatibility checks and lineage tracking.

The platform should not require every system to use the same database, programming language, serialization format, or message broker.

## 2. Design Principles

### 2.1 Domain Ownership

Each model is owned by exactly one domain. The owning domain controls the canonical definition, lifecycle, versioning, access policy, and deprecation policy for that model.

Other domains may consume source models only through explicitly declared projections or subscriptions.

### 2.2 Immutable Contracts

Published model versions and projection versions are immutable. Any incompatible change must create a new version.

Mutable drafts may exist before publication, but published contracts must be stable so downstream systems can rely on them.

### 2.3 Platform-Neutral Definitions

Model and projection definitions must not depend on a specific database or streaming platform.

Database and stream integrations are expressed through adapter bindings. The same logical model should be usable with PostgreSQL, MongoDB, Kafka, Pulsar, NATS, or other supported systems when the adapter capabilities are sufficient.

### 2.4 Explicit Derivation

All derived data must be declared. Field renames, type conversions, computed fields, filters, joins, aggregations, and materialized replicas must be traceable back to their source models and source fields.

### 2.5 Compatibility Before Runtime

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

```yaml
domain: customer
owner: customer-platform
description: Customer identity and lifecycle data.
```

### 3.2 Model

A model is a canonical business entity, event, value object, or aggregate owned by a domain.

Required properties:

- `domain`: Owning domain.
- `name`: Unique model name within the domain.
- `kind`: `entity`, `event`, `value_object`, or `aggregate`.
- `identity`: Key definition for addressable records when applicable.
- `versions`: Published model versions.

Example:

```yaml
domain: customer
model: Customer
kind: entity
```

### 3.3 Model Version

A model version is an immutable schema and semantic contract for a model.

Required properties:

- `version`: Integer or semantic version.
- `status`: `draft`, `published`, `deprecated`, or `retired`.
- `fields`: Field definitions.
- `identity`: Identity fields for entities and aggregates.
- `constraints`: Optional validation constraints.
- `metadata`: Optional classification, documentation, and ownership metadata.

Example:

```yaml
domain: customer
model: Customer
version: 2
status: published

identity:
  key: customerId

fields:
  customerId:
    type: string
    required: true
  legalName:
    type: string
    required: true
  email:
    type: string
    format: email
    classification: pii
  status:
    type: enum
    values: [active, blocked, deleted]
  createdAt:
    type: timestamp
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
- `sources`: Source model versions.
- `identity`: Target identity, if materializable.
- `fields`: Target fields and derivation rules.

Example:

```yaml
domain: billing
projection: BillingCustomer
version: 1

sources:
  - domain: customer
    model: Customer
    version: 2
    alias: c

identity:
  key: billingCustomerId

fields:
  billingCustomerId:
    from: c.customerId
  name:
    from: c.legalName
  invoiceEmail:
    from: c.email
  isBillable:
    expression: c.status == "active"
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

Example:

```yaml
subscription: billing-customer-replica
projection: billing.BillingCustomer.v1

source:
  type: stream
  model: customer.Customer.v2

target:
  type: database
  adapter: postgres
  table: billing_customers

delivery:
  mode: at_least_once
  idempotencyKey: billingCustomerId
  deadLetter: billing-customer-replica-dlq
```

### 3.6 Adapter Binding

An adapter binding connects a logical model, projection, subscription, or materialization to a concrete backend.

Adapter bindings must be separate from model definitions.

Example:

```yaml
binding: customer-postgres
model: customer.Customer.v2
adapter: postgres

storage:
  table: customers
  primaryKey: customer_id

fieldMappings:
  customerId: customer_id
  legalName: legal_name
  createdAt: created_at
```

## 4. Type System

The core type system must support:

- `string`
- `boolean`
- `integer`
- `decimal`
- `float`
- `timestamp`
- `date`
- `time`
- `duration`
- `uuid`
- `binary`
- `enum`
- `array`
- `object`
- `map`
- `reference`

Each field may declare:

- `required`
- `nullable`
- `default`
- `description`
- `format`
- `classification`
- `deprecated`
- `replacedBy`
- `constraints`

Example:

```yaml
email:
  type: string
  format: email
  required: false
  classification: pii
  description: Primary customer email address.
```

## 5. Projection Semantics

### 5.1 Field Selection

A projection may expose a subset of source fields.

```yaml
fields:
  customerId:
    from: c.customerId
  name:
    from: c.legalName
```

### 5.2 Field Rename

Renames must be expressed as projection mappings, not as implicit aliases.

```yaml
fields:
  invoiceEmail:
    from: c.email
```

### 5.3 Computed Fields

Computed fields may use deterministic expressions over source fields.

```yaml
fields:
  isActive:
    expression: c.status == "active"
```

The expression language must be deterministic, side-effect free, and validateable by the planner.

### 5.4 Filters

A projection may filter source records.

```yaml
filter: c.status != "deleted"
```

### 5.5 Joins

A projection may join multiple source models when join keys and cardinality are declared.

```yaml
sources:
  - domain: order
    model: Order
    version: 3
    alias: o
  - domain: customer
    model: Customer
    version: 2
    alias: c

joins:
  - type: left
    left: o.customerId
    right: c.customerId
```

The planner must reject joins that cannot be executed by the selected runtime or adapters.

### 5.6 Aggregations

Aggregations are projections with grouping and aggregate functions.

```yaml
domain: analytics
projection: CustomerOrderSummary
version: 1

sources:
  - domain: order
    model: Order
    version: 3
    alias: o

groupBy:
  customerId: o.customerId

fields:
  customerId:
    from: o.customerId
  totalOrders:
    aggregate: count(o.orderId)
  lifetimeValue:
    aggregate: sum(o.totalAmount)
  lastOrderAt:
    aggregate: max(o.createdAt)
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

Example:

```yaml
adapter: postgres
capabilities:
  storage: true
  transactions: true
  joins: true
  aggregations: true
  jsonFields: true
  cdc: logical_decoding
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

### 8.2 Projection Versioning

Projection versions are immutable once published.

A projection version must declare exact source model versions unless explicitly configured to accept a compatible version range.

Example:

```yaml
sources:
  - model: customer.Customer
    version: ">=2 <3"
```

Version ranges must be resolved to concrete versions at planning time.

### 8.3 Deprecation

Deprecation must be explicit and traceable.

```yaml
email:
  type: string
  deprecated: true
  replacedBy: primaryEmail
  removalAfter: 2027-01-01
```

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

The system should generate artifacts from the canonical internal representation.

Supported initial artifacts:

- JSON Schema.
- OpenAPI schemas.
- SQL DDL.
- TypeScript types.
- Avro schemas.
- Protobuf schemas.

Generated artifacts must include model version metadata.

## 12. Storage Model for Registry

The registry should be persisted using relational tables or equivalent collections.

Minimum logical entities:

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

Published definitions should also be stored as complete immutable documents to preserve exact historical contracts.

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

## 17. MVP Scope

The first version should include:

- Domain registry.
- Model definition and immutable publishing.
- Projection definition with field selection, rename, simple expressions, and filters.
- Exact source version references.
- Compatibility checks for additive and breaking changes.
- Lineage tracking.
- PostgreSQL storage adapter.
- Kafka stream adapter.
- Materialized projection into PostgreSQL.
- JSON Schema and TypeScript generation.
- Basic CLI or API for publishing and validating definitions.

The first version should defer:

- Multi-source joins.
- Stateful aggregations.
- Windowed aggregations.
- Multiple stream backends.
- Multiple database backends.
- Advanced policy engine.
- Visual modeling UI.
- Automatic migration generation.

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

These decisions should be resolved before implementation:

- Whether versions are integers, semantic versions, or both.
- Whether the definition DSL is YAML-first, JSON-first, or code-first.
- Which expression language to use for computed fields.
- Whether model identity supports composite keys in MVP.
- Whether projections can reference compatible version ranges in MVP.
- Whether registry state is stored relationally, document-first, or both.
- Whether runtime plans are interpreted or compiled into generated code.

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


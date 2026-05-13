# Platform Usage Scenarios Specification

## 1. Purpose

This document describes how Modellable is used across different platform categories. Each scenario defines the operational context, recommended adapter bindings, projection patterns, consistency guarantees, and constraints specific to that deployment target.

Modellable's platform-neutral design means the same canonical model definitions apply regardless of the target system. What changes per scenario is the adapter binding configuration, materialization strategy, and operational expectations.

### Data Modelling Phase Boundary

The scenarios in this document represent **Phase 5** of the Modellable implementation roadmap — runtime and event/API targets. They must not be built before the logical data modelling layer is stable.

The preceding phases focus on logical modelling only:

| Phase | Focus | Key Tools |
| :--- | :--- | :--- |
| 1 | Local modelling compiler | Python, pydantic, ruamel.yaml, jsonschema, json-schema-to-typescript, Markdown |
| 2 | Artifact registry | Apicurio Registry |
| 3 | Catalog / governance sync | OpenMetadata |
| 4 | Contract interchange | ODCS, Data Contract CLI |
| 5 | Runtime targets (this document) | CDC, streaming, materialization, event/API formats |

The following runtime integrations are explicitly deferred until Phase 5:

```
Kafka runtime provisioning
Redis materialisers
ClickHouse loaders
Feast integration
API gateways (Kong, AWS API Gateway, Zilla)
Confluent stream governance
dbt execution
Great Expectations execution
Soda execution
Custom registry
Custom UI
```

These pull the design into runtime concerns before the logical model is stable. All scenarios in this document should be read as forward-looking specifications for Phase 5, not immediate implementation targets.

---

## 2. Scenario Index

| Scenario | Primary Need | Typical Backends |
| :--- | :--- | :--- |
| [Data Warehouse](#3-data-warehouse-analytical--olap) | Historical analytics, aggregation | ClickHouse, Snowflake, DuckDB, BigQuery |
| [High-Performance Internet Services](#4-internet-facing-high-performance-services) | Low-latency reads, high write throughput | PostgreSQL, Redis, MongoDB, Cassandra |
| [Event-Driven Microservices](#5-event-driven-microservices) | Async coupling, domain events, fan-out | Kafka, NATS JetStream, Pulsar |
| [Machine Learning and Feature Stores](#6-machine-learning-and-feature-stores) | Point-in-time correct features, training sets | DuckDB, Redis, Feast, custom stores |
| [Third-Party and API Consumers](#7-third-party-and-api-consumers) | Stable contracts, versioned access, policy enforcement | REST APIs, GraphQL, gRPC, OpenAPI |
| [Audit, Compliance, and Regulatory Systems](#8-audit-compliance-and-regulatory-systems) | Immutable history, lineage evidence, data classification | Append-only stores, object storage, WORM |

---

## 3. Data Warehouse (Analytical / OLAP)

### 3.1 Context

Data warehouses consume large volumes of domain data for historical analysis, aggregation, and business intelligence. They are typically write-once-read-many systems optimized for scan-heavy queries rather than point lookups.

In a Modellable deployment, the data warehouse is a **materialisation target**—projections are pushed into it continuously or on a schedule. The warehouse does not own domain models; it consumes them.

Key requirements for this scenario:

- Bulk ingestion with minimal per-row overhead.
- Schema evolution handled gracefully (additive changes preferred).
- Column-level lineage preserved in warehouse metadata.
- PII and classification constraints enforced before rows land.
- Support for historical snapshots and slowly-changing-dimension (SCD) patterns.

### 3.2 Supported Backends

| Backend | Adapter | Notes |
| :--- | :--- | :--- |
| ClickHouse | `ClickHouseAdapter` | High-throughput inserts via async batching; ReplacingMergeTree for upserts |
| Snowflake | `SnowflakeAdapter` | Bulk COPY INTO staging table + MERGE; schema binding via Snowflake `VARIANT` for flexibility |
| DuckDB | `DuckDBAdapter` | Local/embedded analytics; useful for development and small deployments |
| BigQuery | `BigQueryAdapter` | Streaming inserts or Storage Write API; partition-based TTL supported |

### 3.3 Projection Patterns

**Append-Only Fact Projection**

Use when you need a full, immutable event history (e.g., all orders ever placed).

```yaml
projection: order_facts
domain: commerce
sources:
  - model: Order
    version: "3"
fields:
  - source: id
    as: order_id
  - source: createdAt
    as: order_created_at
  - source: totalAmountCents
    as: total_amount_cents
  - source: status
    as: order_status
materialisation:
  strategy: append
  partitionBy: order_created_at
  granularity: day
```

**Current-State Dimension Projection (SCD Type 1)**

Use when the warehouse only needs the latest known value for each entity key.

```yaml
projection: customer_dimension
domain: customer
sources:
  - model: Customer
    version: "2"
fields:
  - source: id
    as: customer_id
  - source: fullName
    as: full_name
  - source: email
    as: email
    classification: pii
  - source: countryCode
    as: country_code
materialisation:
  strategy: upsert
  key: customer_id
```

**Aggregation Projection**

Use when the warehouse should store pre-aggregated summaries rather than raw rows.

```yaml
projection: daily_revenue_summary
domain: commerce
sources:
  - model: Order
    version: "3"
fields:
  - expression: "truncate(createdAt, 'day')"
    as: revenue_date
    type: date
  - expression: "sum(totalAmountCents)"
    as: total_revenue_cents
    type: int64
  - expression: "count(id)"
    as: order_count
    type: int64
groupBy:
  - revenue_date
materialisation:
  strategy: overwrite_partition
  partitionBy: revenue_date
```

### 3.4 Adapter Binding Example

```yaml
binding: warehouse-clickhouse
adapter: clickhouse
role: sink
config:
  host: clickhouse.internal
  port: 8443
  database: modellable_warehouse
  tls: true
  batchSize: 5000
  flushIntervalMs: 2000
  tableEngine: ReplacingMergeTree
```

### 3.5 Consistency and Delivery Guarantees

Data warehouses operate with **at-least-once delivery** and **idempotent materialisation**:

- Each event arriving from the stream includes a `sequence` field used as a deduplication key.
- Upsert projections use the declared key for idempotency. Duplicates are collapsed.
- Append projections use the event `id` for deduplication at ingestion.
- Backfill/replay is supported: the stream adapter's `Seek` method rewinds to a point in time and re-materialises.

### 3.6 Operational Constraints

- **Schema evolution:** Additive changes (new fields) are applied automatically. Removals or type changes require a new projection version and a coordinated migration window.
- **Batch size tuning:** High-throughput warehouses perform best with large batches. Configure `batchSize` and `flushIntervalMs` to balance latency against throughput.
- **PII enforcement:** Fields with `classification: pii` must use a projection-level transform (hash, mask, or exclusion) before the binding writes them to the warehouse. The compiler rejects bindings that would expose raw PII to a warehouse adapter without an explicit transform declaration.
- **Cost controls:** Warehouses billed per query or per byte scanned should use partition pruning via `partitionBy` in the projection definition.

---

## 4. Internet-Facing High-Performance Services

### 4.1 Context

Internet-facing services need data that is:

- **Fast to read** — median latency under 10 ms for point lookups.
- **Always available** — tolerant of upstream outages via a local replica.
- **Consistent enough** — reads reflect writes within a bounded lag (typically seconds).
- **Scoped** — services receive only the fields they are authorised to read; no overfetch.

In this scenario Modellable materialises a per-service projection into a low-latency store (e.g., Redis, Cassandra, or MongoDB) and keeps it in sync via a stream subscription. The service reads from its local projection store; it never queries the canonical source database directly.

### 4.2 Supported Backends

| Backend | Adapter | Notes |
| :--- | :--- | :--- |
| Redis / Valkey | `RedisAdapter` | Hash-per-record; sub-millisecond reads; bounded TTL for implicit expiry |
| MongoDB | `MongoAdapter` | Document-per-record; flexible schema; secondary index support |
| Cassandra / ScyllaDB | `CassandraAdapter` | Wide-column; ideal for time-series or write-heavy projections |
| PostgreSQL (read replica) | `PostgresAdapter` | Familiar SQL access; suitable for mid-scale services |

### 4.3 Projection Patterns

**Service-Scoped Read Model**

Each service declares a projection containing only the fields it needs. Modellable enforces that no undeclared field reaches the service's store.

```yaml
projection: customer_profile_for_checkout
domain: customer
sources:
  - model: Customer
    version: "2"
fields:
  - source: id
    as: customer_id
  - source: fullName
    as: full_name
  - source: defaultShippingAddressId
    as: shipping_address_id
  - source: preferredCurrencyCode
    as: currency_code
  - source: loyaltyTierId
    as: loyalty_tier
materialisation:
  strategy: upsert
  key: customer_id
subscription:
  source: customer-events
  adapter: kafka-main
  consumerGroup: checkout-svc-customer-profile
```

**Denormalised Join Projection**

Joins two source models into one flattened document optimised for read. The join is declared explicitly so lineage covers both sources.

```yaml
projection: order_with_customer
domain: commerce
sources:
  - model: Order
    version: "3"
    alias: o
  - model: Customer
    version: "2"
    alias: c
    joinOn:
      left: o.customerId
      right: c.id
fields:
  - source: o.id
    as: order_id
  - source: o.totalAmountCents
    as: total_amount_cents
  - source: c.fullName
    as: customer_name
  - source: c.countryCode
    as: customer_country
materialisation:
  strategy: upsert
  key: order_id
```

### 4.4 Adapter Binding Example

```yaml
binding: checkout-redis-sink
adapter: redis
role: sink
config:
  host: redis.checkout.internal
  port: 6380
  tls: true
  keyPrefix: "modellable:customer_profile:"
  defaultTtlSeconds: 3600
  serialisation: msgpack
```

### 4.5 Consistency and Delivery Guarantees

- **Replication lag:** Projections are updated within the stream's consumer lag window. Typical target: under 2 seconds end-to-end from a committed write on the source.
- **Stale reads:** Services must tolerate bounded staleness. If strict consistency is required for a field, that field should be read from the canonical source directly (outside Modellable).
- **Failure isolation:** A stream adapter outage does not take down the service's read path. The local projection store serves reads from the last-materialised state.
- **Backpressure:** High-throughput services must configure the `consumerGroup` lag alert threshold so the Modellable runtime can signal when the projection is falling behind acceptable lag bounds.

### 4.6 Operational Constraints

- **Key design:** Choose projection keys carefully. Hotspot keys (e.g., a single tenant with millions of records) must be sharded; declare `shardKey` in the binding config if the adapter supports it.
- **TTL vs. delete events:** For Redis, records can expire via TTL. Ensure the stream subscription handles `delete` events from the CDC adapter to remove records explicitly rather than relying solely on TTL.
- **Capacity planning:** Materialised projections duplicate data. Budget storage for the per-service copy and ensure ownership documentation references the canonical source to avoid treating the replica as authoritative.
- **No writes back:** Internet-facing services must not write mutations back through the projection store. All writes must go through the canonical domain's write path.

---

## 5. Event-Driven Microservices

### 5.1 Context

Microservices that communicate asynchronously via domain events need:

- A stable, versioned event schema they can subscribe to.
- Confidence that event fields are traceable to a domain owner.
- The ability to consume only relevant events without coupling to the publisher's internal schema.
- Replay capability for backfill and recovery.

Modellable treats each model version as an **event contract**. A service subscribes to a model's event stream and receives CloudEvents envelopes conforming to that contract.

### 5.2 Supported Backends

| Backend | Adapter | Notes |
| :--- | :--- | :--- |
| Kafka | `KafkaAdapter` | Log-based; durable replay; consumer group offset management |
| NATS JetStream | `NatsAdapter` | Lightweight; push or pull consumers; built-in replay via subjects |
| Pulsar | `PulsarAdapter` | Multi-tenant; tiered storage for long retention |

### 5.3 Event Subscription Pattern

A service declares its subscription as a projection with a stream source and no materialisation target (the service handles its own state):

```yaml
projection: payment_service_order_events
domain: payments
sources:
  - model: Order
    version: "3"
    domain: commerce
fields:
  - source: id
    as: order_id
  - source: status
    as: order_status
  - source: totalAmountCents
    as: amount_cents
  - source: customerId
    as: customer_id
subscription:
  source: commerce.order.v3
  adapter: kafka-main
  consumerGroup: payment-svc-order-sub
  fromOffset: earliest
  filter:
    expression: "order_status in ['payment_pending', 'payment_failed']"
```

The `filter` expression (evaluated using CEL) allows the subscriber to receive only events matching its operational interest, reducing processing overhead without changing the upstream contract.

### 5.4 Topic and Subject Naming

Stream topic names are derived from the model definition to ensure consistency:

```
<domain>.<model_name_snake_case>.v<version_major>

# Examples:
commerce.order.v3
customer.customer.v2
inventory.product_listing.v1
```

Adapters generate the topic name automatically from the model metadata. Manual overrides are permitted via binding config but must be declared explicitly and are flagged in lineage output as non-standard.

### 5.5 Adapter Binding Example

```yaml
binding: kafka-main
adapter: kafka
role: stream
config:
  brokers:
    - kafka-1.internal:9092
    - kafka-2.internal:9092
  tls: true
  saslMechanism: SCRAM-SHA-512
  replicationFactor: 3
  retentionMs: 604800000   # 7 days
  compressionType: lz4
```

### 5.6 Operational Constraints

- **Consumer lag alerting:** Each `consumerGroup` should be monitored. Excessive lag indicates a downstream service is not keeping up and may miss time-sensitive events.
- **Schema compatibility:** Modellable enforces that a new model version published to a topic is backward-compatible with the previous version before the topic is created or migrated. Breaking changes require routing to a new topic (`v4`, etc.).
- **Dead-letter handling:** Events that fail processing after the configured retry count are routed to a dead-letter topic (`<topic>.dlq`). Operators must monitor and replay or discard DLQ events.
- **Ordering guarantees:** Kafka partitioning uses the model's primary key by default to maintain per-entity ordering. Projections that aggregate across entities cannot rely on global ordering.

---

## 6. Machine Learning and Feature Stores

### 6.1 Context

ML systems need data that is:

- **Point-in-time correct:** Training features must reflect the value of a property as it was at the moment a label was generated, not its current value.
- **Consistent between training and serving:** The same feature definition must produce the same value in both batch training pipelines and online inference requests.
- **Governed:** Features derived from PII fields must carry that classification forward so they are not inadvertently exposed.

Modellable provides the canonical source definitions and lineage backbone. Feature store integrations consume projections from Modellable rather than querying source systems directly.

### 6.2 Supported Backends

| Backend | Adapter | Notes |
| :--- | :--- | :--- |
| Feast | `FeastAdapter` | Offline store (DuckDB/BigQuery) + online store (Redis) integration |
| Redis (online) | `RedisAdapter` | Low-latency feature serving at inference time |
| DuckDB (offline) | `DuckDBAdapter` | Local development and small-scale training |
| Object Storage (S3/GCS) | `ObjectStorageAdapter` | Parquet-based feature snapshots for training jobs |

### 6.3 Projection Patterns

**Offline Training Snapshot**

```yaml
projection: customer_features_training
domain: ml-platform
sources:
  - model: Customer
    version: "2"
  - model: OrderAggregate
    version: "1"
    joinOn:
      left: Customer.id
      right: OrderAggregate.customerId
fields:
  - source: Customer.id
    as: customer_id
  - source: Customer.accountAgeDays
    as: account_age_days
  - source: OrderAggregate.lifetimeOrderCount
    as: ltv_order_count
  - source: OrderAggregate.avgOrderValueCents
    as: avg_order_value_cents
materialisation:
  strategy: snapshot
  snapshotAt: "{{ training_cutoff_timestamp }}"
  format: parquet
  destination: s3://ml-features/customer/
```

**Online Feature Projection**

```yaml
projection: customer_features_online
domain: ml-platform
sources:
  - model: Customer
    version: "2"
fields:
  - source: id
    as: customer_id
  - source: accountAgeDays
    as: account_age_days
  - source: loyaltyTierId
    as: loyalty_tier
materialisation:
  strategy: upsert
  key: customer_id
subscription:
  source: customer.customer.v2
  adapter: kafka-main
  consumerGroup: ml-platform-online-features
```

### 6.4 Operational Constraints

- **Training/serving skew:** Any change to a feature projection definition must be versioned. The training snapshot and the online projection must reference the same projection version to avoid skew.
- **PII propagation:** Fields derived from PII sources carry the `classification: pii` flag. The ML platform must apply masking or aggregation before features reach model artefacts that are exported externally.
- **Point-in-time joins:** Offline snapshot projections must specify `snapshotAt` to avoid data leakage from future values. The runtime rejects snapshots that reference a timestamp in the future.

---

## 7. Third-Party and API Consumers

### 7.1 Context

External consumers (partner APIs, public-facing services, embedded clients) need:

- A stable contract that does not change without notice.
- Access scoped to only the fields they are permitted to read.
- Generated client artefacts (OpenAPI schema, TypeScript types, Protobuf) that match the projection exactly.

Modellable generates these artefacts from projection definitions. The projection version becomes the API version.

### 7.2 Supported Output Formats

| Format | Use Case |
| :--- | :--- |
| OpenAPI 3.1 | REST APIs; importable into API gateways and documentation tools |
| JSON Schema (Draft 2020-12) | Generic contract validation; webhook payloads |
| TypeScript | Frontend and Node.js SDK generation |
| Protobuf (proto3) | gRPC services; binary efficiency; Buf registry integration |
| GraphQL SDL | GraphQL APIs; type definitions generated from projection fields |

### 7.3 Projection Pattern

```yaml
projection: public_product_listing
domain: catalogue
sources:
  - model: ProductListing
    version: "2"
fields:
  - source: id
    as: product_id
  - source: name
    as: product_name
  - source: descriptionShort
    as: description
  - source: priceAmountCents
    as: price_cents
  - source: currencyCode
    as: currency
  - source: imageUrl
    as: image_url
  - source: availabilityStatus
    as: availability
access:
  visibility: public
  rateLimit: 1000rpm
  authentication: api_key
```

### 7.4 Contract Stability Rules

- A published projection version must not have fields removed or renamed without incrementing the version.
- Additive changes (new optional fields) are permitted within the same version.
- Deprecation is announced via the `deprecated` flag on a field; the runtime includes a `Deprecation` response header on affected API responses.
- Consumers referencing a deprecated projection version receive a migration guide generated from the diff between their version and the current version.

### 7.5 Operational Constraints

- **API gateway integration:** The generated OpenAPI document can be imported directly into Kong, AWS API Gateway, or similar tools. The gateway enforces rate limits and authentication declared in the projection's `access` block.
- **Webhook delivery:** Projections with `visibility: public` can be subscribed to as webhooks. The Modellable runtime signs each payload with HMAC-SHA256 using the consumer's registered secret.
- **Versioned URLs:** Generated REST paths follow the convention `/v{version}/{resource}`. Clients should pin to a specific version; the runtime keeps prior versions active until their deprecation window closes.

---

## 8. Audit, Compliance, and Regulatory Systems

### 8.1 Context

Regulatory and compliance workloads require:

- **Immutable history:** Records must not be altered or deleted after the retention period begins.
- **Lineage evidence:** Auditors need proof that a value in a report originated from a specific canonical model field at a specific version.
- **Data classification enforcement:** PII, financial, and health data must be handled according to jurisdiction-specific rules.
- **Access logging:** All reads of sensitive projections must be logged with identity and timestamp.

Modellable's immutable contract model and property-level lineage make it well-suited as the source of truth for compliance artefacts.

### 8.2 Supported Backends

| Backend | Adapter | Notes |
| :--- | :--- | :--- |
| Object Storage (S3/GCS WORM) | `ObjectStorageAdapter` | Write-once buckets; tamper-evident; low cost for long retention |
| PostgreSQL (audit log) | `PostgresAdapter` | Append-only partitioned table; logical WAL export for external SIEM |
| Dedicated audit stores | `ImmutableStoreAdapter` | Immudb or similar; cryptographic proof of immutability |

### 8.3 Projection Patterns

**Regulatory Snapshot**

Point-in-time snapshot of all fields required by a regulatory report. Frozen at the reporting date.

```yaml
projection: gdpr_data_subject_export
domain: compliance
sources:
  - model: Customer
    version: "2"
fields:
  - source: id
    as: subject_id
  - source: fullName
    as: full_name
    classification: pii
  - source: email
    as: email
    classification: pii
  - source: countryCode
    as: country_code
  - source: createdAt
    as: account_created_at
  - source: deletionRequestedAt
    as: deletion_requested_at
materialisation:
  strategy: snapshot
  retentionYears: 7
  immutable: true
  encryption: aes256_at_rest
access:
  requiredRole: compliance-officer
  auditLog: true
```

**Append-Only Audit Trail**

Every state change to a model appended without deletion.

```yaml
projection: order_audit_trail
domain: compliance
sources:
  - model: Order
    version: "3"
fields:
  - source: id
    as: order_id
  - source: status
    as: order_status
  - source: updatedAt
    as: changed_at
  - source: updatedBy
    as: changed_by
materialisation:
  strategy: append
  immutable: true
  partitionBy: changed_at
  granularity: month
```

### 8.4 Lineage Evidence

The Modellable registry can produce a lineage report for any field in any projection. The report is a signed document containing:

- The source model, version, and field.
- The projection definition at the time of materialisation.
- The owning domain and contact.
- The governance classifications applied.
- A hash of the relevant model version for tamper detection.

This report can be provided to auditors as evidence that a value in a compliance export originated from a governed, owned source.

### 8.5 Operational Constraints

- **Retention enforcement:** The `retentionYears` field is enforced by the runtime. The materialiser will not delete records within the retention window, even if a delete event arrives from the source.
- **Right-to-erasure handling:** GDPR and similar regulations require deletion on request. Modellable separates the compliance audit trail (append-only, retained) from the operational projection (deletable). Erasure is applied to operational stores; the audit trail retains a tombstone record with PII fields replaced by a deletion marker and the request timestamp.
- **Access logging:** Projections with `auditLog: true` cause the runtime to emit an access event for every read. Access events are written to the audit log backend and include the caller identity, timestamp, and fields returned.
- **Encryption:** Fields classified as `pii` or `confidential` in projections targeting immutable stores must declare an encryption scheme. The compiler rejects bindings that would write classified fields to an immutable store in plaintext.

---

## 9. Choosing a Scenario

Multiple scenarios often apply to the same deployment. Use this table to identify which specs apply:

| If you need... | Primary scenario | Also read |
| :--- | :--- | :--- |
| Historical reports and dashboards | [Data Warehouse](#3-data-warehouse-analytical--olap) | [Audit & Compliance](#8-audit-compliance-and-regulatory-systems) |
| Sub-10ms reads in a user-facing product | [High-Performance Services](#4-internet-facing-high-performance-services) | [Third-Party Consumers](#7-third-party-and-api-consumers) |
| Decoupled service communication | [Event-Driven Microservices](#5-event-driven-microservices) | [High-Performance Services](#4-internet-facing-high-performance-services) |
| Training ML models and serving predictions | [ML and Feature Stores](#6-machine-learning-and-feature-stores) | [Data Warehouse](#3-data-warehouse-analytical--olap) |
| Partner integrations and public APIs | [Third-Party Consumers](#7-third-party-and-api-consumers) | [High-Performance Services](#4-internet-facing-high-performance-services) |
| Regulatory reporting, GDPR, audit trails | [Audit & Compliance](#8-audit-compliance-and-regulatory-systems) | [Data Warehouse](#3-data-warehouse-analytical--olap) |

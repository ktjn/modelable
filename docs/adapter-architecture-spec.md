# Design: Multi-Backend Adapter Architecture

This document defines the architecture for supporting multiple databases and streaming services in the Modelable platform using the **Ports and Adapters (Hexagonal)** pattern.

## 1. Objectives

- **Backend Agnostic:** The core projection and registry logic must not depend on specific database or streaming implementations.
- **Pluggability:** Adding a new database (e.g., MongoDB) or stream (e.g., NATS) should require implementing a new adapter, not changing core code.
- **Consistency:** Maintain "Effectively-Once" semantics across different backend combinations.
- **Standardization:** Use industry standards like **CloudEvents** for data interchange.

---

## 2. Core Abstractions (The "Ports")

### 2.1 Storage Adapter (`StoragePort`)
Responsible for reading from source models and writing to materialized projections.

| Method | Description |
| :--- | :--- |
| `Connect(config)` | Establish connection to the database. |
| `Query(projection, filter)` | Execute a query against a projection (for batch/on-demand). |
| `Upsert(projection, record)` | Perform an idempotent write of a projected record. |
| `Delete(projection, key)` | Remove a record from a projection. |
| `GetSchema()` | Introspect the database to provide metadata to the Registry. |

**Candidate Implementations:** `PostgresAdapter`, `MongoAdapter`, `SnowflakeAdapter`.

### 2.2 Stream Adapter (`StreamPort`)
Responsible for publishing and subscribing to versioned model events.

| Method | Description |
| :--- | :--- |
| `Publish(envelope)` | Send a versioned event to a topic/subject. |
| `Subscribe(topic, handler)` | Listen for events and trigger the Materializer. |
| `CommitOffset(id)` | Mark an event as successfully processed for durability. |
| `Seek(offset/time)` | Reposition the consumer for replay/backfill. |

**Candidate Implementations:** `KafkaAdapter`, `NatsAdapter`, `PulsarAdapter`.

### 2.3 CDC Adapter (`CapturePort`)
Responsible for capturing changes from a source database and converting them to the internal event format.

| Method | Description |
| :--- | :--- |
| `StartCapture(model)` | Begin tailing the transaction log for a specific model. |
| `StopCapture()` | Cease capture. |
| `GetStatus()` | Report on lag and health. |

**Candidate Implementations:** `DebeziumAdapter` (wraps Debezium Server), `PostgresLogicalAdapter` (native).

---

## 3. Standardized Event Envelope (CloudEvents)

To ensure interoperability, all internal events will follow the **CloudEvents 1.0** specification.

```json
{
  "specversion": "1.0",
  "id": "evt_abc123",
  "source": "/modelable/domain/customer/model/Customer/v2",
  "type": "modelable.event.upsert",
  "time": "2026-05-12T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    "key": "cust_456",
    "sequence": "00000123",
    "payload": { ... }
  },
  "modelable_version": "2",
  "modelable_domain": "customer"
}
```

The CloudEvents `data` attribute carries the Modelable-specific envelope defined in `modelable-system-spec.md` §6.1 (`domain`, `model`, `version`, `operation`, `key`, `sequence`, `timestamp`, `payload`). Modelable-defined fields that do not fit standard CloudEvents attributes are placed as CloudEvents extension attributes (e.g., `modelable_version`, `modelable_domain`). The `source` attribute encodes the model path so that consumers can route events without parsing the payload.

---

## 4. Interaction Flow: Cross-Backend Projection

Example: Projecting **PostgreSQL (Source)** via **NATS (Stream)** into **MongoDB (Target)**.

1.  **Capture:** `PostgresCaptureAdapter` tails the WAL and produces a **CloudEvent**.
2.  **Transport:** `NatsStreamAdapter` publishes the event to the `customer.Customer.v2` subject.
3.  **Process:** The `ProjectionEngine` receives the event from NATS and applies the transformation logic.
4.  **Materialize:** `MongoStorageAdapter` performs an `upsert` into the target collection using the `id` as the shard key.

---

## 5. Adapter Configuration (Adapter Bindings)

Bindings map logical platform concepts to physical backend instances.

```yaml
# Binding for a source model
binding: customer-db-source
adapter: postgres
config:
  host: localhost
  port: 5432
  database: customer_svc
  capture: logical_decoding

# Binding for the transport layer
binding: global-transport
adapter: nats
config:
  url: "nats://localhost:4222"
  jetstream: true

# Binding for a projection target
binding: billing-replica
adapter: mongodb
config:
  uri: "mongodb://localhost:27017"
  collection: billing_customers
```

---

## 6. Registry Integration

The **Model Registry** (Section 7.1 of the Spec) stores these bindings. When a projection is "Planned" (Section 7.2), the Planner:
1.  Loads the **Source Binding** to identify the Capture adapter.
2.  Loads the **Transport Binding** to identify the Stream adapter.
3.  Loads the **Target Binding** to identify the Storage adapter.
4.  Validates that all three adapters are compatible with the required projection logic (e.g., ensuring the target supports `upsert` if requested).

---

## 7. Artifact Output Adapters

The runtime adapters above (Sections 2–5) handle live data movement. A separate set of **artifact output adapters** handles export from the normalized model graph to external tools. These are compiler-phase concerns, not runtime concerns.

```
Modelable DSL
   |
   v
Parser + Semantic Validator
   |
   v
Normalized Model Graph
   |
   |-- JSON Schema       -> Apicurio Registry
   |-- Markdown docs     -> Static site (MkDocs, Docusaurus, GitHub Pages)
   |-- TypeScript types  -> Consumer SDKs
   |-- OpenMetadata JSON -> OpenMetadata catalog
   |-- ODCS export       -> Data Contract CLI
   `-- Registry artifacts
```

### 7.1 Apicurio Registry Adapter

Stores generated artifacts and manages version lifecycle. Supported formats: JSON Schema, Avro, Protobuf, OpenAPI, AsyncAPI, and GraphQL (post-MVP).

Artifact IDs follow the convention `<domain>.<name>.v<version>`:

```
customer.Customer.v1
billing.BillingCustomer.v1
commerce.OrderPlaced.v3
```

CLI commands:

```bash
modelable compile ./models --target json-schema --out ./dist/jsonschema
modelable publish apicurio ./dist/jsonschema
modelable pull apicurio customer.Customer@1
```

Apicurio is an artifact registry only. It is not the Modelable source of truth.

For the full mapping tables and boundaries, see `external-tools-data-modelling.md` §4.

### 7.2 OpenMetadata Catalog Adapter

Exports model and lineage metadata to OpenMetadata for catalog UI, ownership, classification tags, and lineage visualization.

CLI commands:

```bash
modelable export openmetadata ./models --out ./dist/openmetadata.json
modelable publish openmetadata ./dist/openmetadata.json
```

OpenMetadata is used for visibility and governance workflows. It is not the projection resolver.

For the full mapping tables and export shape, see `external-tools-data-modelling.md` §5.

### 7.3 ODCS / Data Contract CLI Adapter

Exports model and projection definitions as Open Data Contract Standard (ODCS) documents for interoperability and CI validation.

CLI commands:

```bash
modelable export odcs customer.Customer@1 --out ./dist/customer.contract.yaml
datacontract lint ./dist/customer.contract.yaml
```

ODCS is an export and interchange format. Modelable's internal model is not forced into ODCS shape.

For the full mapping tables, see `external-tools-data-modelling.md` §6.

---

## 8. Phase Notes

The runtime adapters (Sections 2–5) and artifact output adapters (Section 7) belong to different implementation phases:

| Phase | Scope | Key Adapters |
| :--- | :--- | :--- |
| 1 | Local Compiler | JSON Schema generator, Markdown generator, TypeScript generator |
| 2 | Artifact Registry | Apicurio Registry adapter |
| 3 | Catalog Sync | OpenMetadata adapter |
| 4 | Interchange | ODCS / Data Contract CLI adapter |
| 5 | Runtime & Targets | StoragePort, StreamPort, CapturePort, Avro, Proto, OpenAPI |

Do not build runtime adapters before the normalized model graph is stable.


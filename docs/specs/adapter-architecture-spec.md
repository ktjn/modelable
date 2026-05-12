# Design: Multi-Backend Adapter Architecture

This document defines the architecture for supporting multiple databases and streaming services in the Modellable platform using the **Ports and Adapters (Hexagonal)** pattern.

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
  "source": "/modellable/domain/customer/model/Customer/v2",
  "type": "modellable.event.upsert",
  "time": "2026-05-12T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    "key": "cust_456",
    "sequence": "00000123",
    "payload": { ... }
  },
  "modellable_version": "2",
  "modellable_domain": "customer"
}
```

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

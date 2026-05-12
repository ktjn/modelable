# Research: Technology Stack Evaluation for Modellable

This document evaluates the technologies for building the Modellable runtime, including source database capture, streaming transport, and target materialization.

## 1. Source Database & CDC (Change Data Capture)

The platform must capture changes from canonical source models without direct coupling.

| Technology | Role | Pros | Cons |
| :--- | :--- | :--- | :--- |
| **Debezium** | Log-based CDC Engine | Industry standard; supports Postgres WAL, MySQL binlog, Mongo oplog. | High ops overhead; usually tied to Kafka Connect. |
| **PostgreSQL (Logical Replication)** | Native CDC Source | Zero external dependencies for Postgres-first MVP. | Requires `wal_level = logical` and manual slot management. |
| **Estuary / Flow** | Managed CDC Pipeline | Unifies batch backfill and real-time streaming; extremely low latency. | Proprietary/Managed service (Gazette-based). |
| **Artie** | CDC-to-Warehouse | Optimized for destination sync and schema evolution. | Narrower focus (analytics sinks). |

**Recommendation:** For the MVP, support **Debezium Server** (standalone) as it can push to multiple sinks (Kafka, NATS, etc.) without requiring the full Kafka Connect cluster.

---

## 2. Streaming Transport Layer

The "backbone" that carries versioned model events between domains.

| Technology | Delivery Guarantees | Strengths | Weaknesses |
| :--- | :--- | :--- | :--- |
| **Kafka** | Effectively-once (via Idempotence/Transactions) | Massive ecosystem; persistent log; high throughput. | Complex to operate; high resource footprint. |
| **Pulsar** | At-least-once / Effectively-once | Built-in multi-tenancy; tiered storage (S3); cloud-native. | Complexity similar to Kafka; smaller community. |
| **NATS JetStream** | At-least-once / Exactly-once (per consumer) | Lightweight; simple to operate; high performance. | Less "big data" ecosystem support than Kafka. |

**Recommendation:** Support **Kafka** as the primary backend for production and **NATS JetStream** as a lightweight alternative for edge or developer-centric deployments.

---

## 3. Target Materialization & Storage

How projections are turned into queryable replicas.

| Technology | Role | Strategy |
| :--- | :--- | :--- |
| **PostgreSQL** | Relational Sink | **Upsert-Driven:** Use `INSERT ... ON CONFLICT` for 1:1 joins. **Differential:** Use `pg_ivm` for complex N:N joins. |
| **ClickHouse / DuckDB** | Analytics Sink | Optimized for high-volume aggregations and columnar queries. |
| **Redis / MongoDB** | Key-Value / Document Sink | Ideal for "Consumer-facing" low-latency read models. |

---

## 4. Implementation Approaches

### 4.1 "Effectively-Once" Delivery
To meet the requirement in Section 6.2, the system should implement:
1.  **Deterministic Envelopes:** Every event must have a `sequence` and `key` (Section 6.1).
2.  **Idempotent Sinks:** The Materializer (Section 7.4) must use the event `key` and `sequence` to ensure that replayed events do not create duplicates (e.g., `upsert` in Postgres based on the source identity).

### 4.2 Projection Materialization Strategies
- **Batch Rebuild:** Scan source database/topic from offset 0 into a temporary table, then swap.
- **Incremental Update:** Stream changes and apply `upsert` or `delete` logic in real-time.
- **Stateful Joins:** 
    - For MVP: Limit to **Lookup Joins** (Stream joins against a static/slow-moving Table).
    - Post-MVP: Use a differential engine (like Flink or Materialize) or `pg_ivm` for Stream-to-Stream joins.

## 5. Summary Matrix for MVP

| Component | Choice |
| :--- | :--- |
| **Primary Source** | PostgreSQL (via Debezium or Logical Decoding) |
| **Streaming Broker** | Kafka (Standard) or NATS (Lightweight) |
| **Materialization Sink** | PostgreSQL |
| **Join Strategy** | Upsert-based Lookup Joins |
| **Consistency Mode** | Effectively-Once (via Idempotent Upserts) |

# Sample Scenarios

This directory contains complete sample scenarios covering a range of Modelable platform types and architectural patterns. Each scenario is defined using the canonical **Modelable IDL (`.mdl`)** format, demonstrating production-realistic definitions across multiple domains.

Use these as illustrative examples or validate them with the CLI (`modelable validate scenarios/<id>/`).

Some scenarios intentionally include future-phase constructs such as `materialisation`, subscriptions, federation, and runtime adapter configuration. Those examples document target platform behavior and may require Phase 5 runtime support even when the core model and projection syntax is valid for Phase 1.

The strict Phase 1 acceptance sample is the separate minimal `samples/mvp/` set defined by the MVP implementation plan. These scenario examples are broader product examples and are not required to pass strict MVP validation unless a scenario explicitly says so.

The `samples/conformance/` fixture is different from the narrative scenarios:
it is a small public regression fixture for generated-artifact behavior that
contributors can run without access to private downstream projects. See
[docs/conformance.md](../docs/conformance.md).

---

## Scenario Index

| # | ID | Title | Platform | Complexity | Relevant Spec |
|---|:---|:------|:---------|:-----------|:--------------|
| 1 | `01-ecommerce-data-warehouse` | E-commerce Analytics Data Warehouse | Data Warehouse | High | [Architecture](../docs/architecture.md) |
| 2 | `02-realtime-fraud-detection` | Real-Time Fraud Detection Service | High-Performance Service | High | [Architecture](../docs/architecture.md) |
| 3 | `03-order-saga-microservices` | Order Fulfillment Saga | Event-Driven Microservices | High | [Architecture](../docs/architecture.md) |
| 4 | `04-credit-risk-feature-store` | Credit Risk ML Feature Store | ML Feature Store | High | [Architecture](../docs/architecture.md) |
| 5 | `05-partner-marketplace-api` | Partner Marketplace API | API Consumer | High | [Architecture](../docs/architecture.md) |
| 6 | `06-gdpr-compliance-audit` | GDPR Compliance and Immutable Audit Trail | Audit & Compliance | High | [Architecture](../docs/architecture.md) |
| 7 | `07-multi-system-master-data` | Enterprise Multi-System Master Data Architecture | Master Data / Data Platform | Very High | [Compiler reference](../docs/compiler-reference.md) |
| 8 | `08-distributed-multi-registry` | Federated Registry Network | Federation / Peer Sync | High | [Compiler reference](../docs/compiler-reference.md) |
| 9 | `09-auto-projections` | Compiler-Generated Projection Contracts | Core Language | Medium | [Language reference](../docs/language-reference.md) §3.7 |
| 10 | `10-impact-analysis` | Breaking-Change Impact Analysis | Core Language | Low | [Language reference](../docs/language-reference.md) §2.7 |
| 11 | `11-fleet-telemetry-type-system` | IoT Fleet Telemetry | Core Language | Medium | [Language reference](../docs/language-reference.md) §2.1, §3.8, §3.9 |

---

## Scenario Summaries

### 1. E-commerce Data Warehouse (`scenarios/01-ecommerce-data-warehouse/`)

A high-traffic marketplace feeds a ClickHouse analytics warehouse with customer lifetime value, acquisition-cohort revenue curves, checkout-funnel conversion rates, and multi-touch campaign attribution.

Key techniques demonstrated:
- Cross-domain joins across `customer`, `commerce`, and `payments`
- HMAC pseudonymisation of PII (email) before warehouse landing
- Append-only funnel facts preserving historical trajectory
- Pre-aggregated nightly cohort summaries (`overwrite_partition` strategy)
- `SummingMergeTree` and `ReplacingMergeTree` engine bindings for ClickHouse
- Shared `semantic` type aliases (`CountryCode`, `CurrencyCode`) referenced across domains as `customer.CountryCode` / `commerce.CurrencyCode`
- `uuid(7)` timestamp-ordered ids for high-volume order, line-item, and payment-transaction streams
- `index` declarations on `Customer` (unique email lookup) and `OrderLineItem` (order rehydration lookup)

Domains: `customer`, `commerce`, `payments`, `analytics`

---

### 2. Real-Time Fraud Detection (`scenarios/02-realtime-fraud-detection/`)

A payment processor requires sub-millisecond fraud signal reads during payment authorisation. Four source models from different domains are denormalised into a single Redis hash per customer, refreshed continuously via Kafka.

Key techniques demonstrated:
- Denormalized multi-source join collapsed into one Redis key for zero-latency lookup
- CEL computed fields for derived risk signals (`velocityDeclineRatio1h`, `isMultiAccountDevice`)
- Separate per-merchant and per-device projections with independent TTLs
- `msgpack` serialisation for space-efficient Redis storage
- TTL-based data freshness guarantees (86400s customer, 3600s merchant)

Domains: `fraud`, `risk`, `payments`

---

### 3. Order Fulfillment Saga (`scenarios/03-order-saga-microservices/`)

A five-service order fulfillment system coordinates via Kafka choreography. Each service subscribes to a filtered projection of domain events from the previous saga step. No service calls another directly.

Key techniques demonstrated:
- Field-scoped projections per consuming service (inventory never sees payment data)
- CEL filter expressions routing only operationally relevant events to each service
- Cross-domain join inside a projection (shipping service needs both payment and order data)
- Per-service dead-letter topics and configurable retry backoff
- Correlation key (`orderId`) propagated across all five event types
- `enableIdempotentProducer` and `acks: all` for exactly-once-at-Kafka semantics

Domains: `commerce`, `inventory`, `payments`, `shipping`, `notifications`

---

### 4. Credit Risk ML Feature Store (`scenarios/04-credit-risk-feature-store/`)

A lending platform's ML team trains and serves a credit scoring model with point-in-time correct features. The same projection version drives both the offline training snapshot (Parquet on S3) and the online Redis serving layer, preventing training/serving skew.

Key techniques demonstrated:
- PIT-correct `pitCutoff` joins preventing future data leakage into training sets
- Three-tier PII handling: raw (internal ML platform), sensitive (annotated), anonymised (export)
- Bureau data bucketing (`credit_score_band`, `utilization_band`) to prevent re-identification
- Offline `snapshot` materialisation with `snapshotAt` template parameter
- Online `upsert` materialisation with Kafka subscription and lag alerting
- Feature staleness indicator (`bureau_report_age_days`)
- `uuid(7)` timestamp-ordered ids for bureau-report ingestion order
- Fixed-width integers (`u16` credit score, `u8` account/inquiry counts) sized to their real value ranges
- `index BureauReport @ 1` with a `sort`-ordered secondary index for "most recent report per customer" lookups

Domains: `ml-credit-risk`, `customer`, `lending`, `credit-bureau`

---

### 5. Partner Marketplace API (`scenarios/05-partner-marketplace-api/`)

A marketplace exposes catalog, inventory, and order data to 500+ seller partners through versioned projections. Modelable generates OpenAPI 3.1, TypeScript, and Protobuf artifacts directly from projection definitions. Per-seller access is enforced via runtime CEL filter parameters.

Key techniques demonstrated:
- Internal-only fields (`supplierCostCents`, `marginCode`) explicitly absent from external projections
- Runtime auth-context filter parameters (`request.sellerId`) for row-level access control
- Artifact generation configuration (`openapi_3_1`, `typescript`, `protobuf`) per projection
- Webhook delivery with HMAC-SHA256 per-partner signing
- Graduated rate limiting per access scope (`catalogue.read` vs `orders.read`)
- `accessControlField` declaration for API gateway integration

Domains: `catalogue`, `inventory`, `commerce`, `marketplace-api`

---

### 6. GDPR Compliance and Audit Trail (`scenarios/06-gdpr-compliance-audit/`)

A healthcare-adjacent SaaS platform handles three simultaneous compliance obligations: GDPR Data Subject Access Requests (DSAR), right-to-erasure with tombstoning, and a 7-year immutable billing audit trail.

Key techniques demonstrated:
- DSAR snapshot collects all PII fields across three source models
- Erasure tombstone replaces PII field values with `'[ERASED]'` literals via CEL expressions
- Append-only consent history for GDPR Article 7 compliance evidence
- WORM S3 binding with `objectLockMode: COMPLIANCE` and KMS encryption
- Immutable billing audit in both S3 WORM and immudb (cryptographic tamper detection)
- `auditLog: true` triggers access event emission on every read of sensitive projections
- Retention enforcement: `retentionYears: 7` on all financial and personal data

Domains: `compliance`, `customer`, `billing`, `audit`

---

### 7. Enterprise Multi-System Master Data Architecture (`scenarios/07-multi-system-master-data/`)

Six authoritative source systems — CRM, IAM, PIM, CPQ, WMS, and PSP — each own a slice of the enterprise master record. They share data through cross-domain `ref<>` links rather than point-to-point APIs. A thin `orders` domain acts as the shared joining point. An ODS layer consolidates these systems into near-real-time operational views for checkout, support, and operations. A ClickHouse data mart provides pre-aggregated facts and snapshots for BI and ML.

Key techniques demonstrated:
- Six authoritative source systems with explicit cross-domain `ref<>` links (CRM → CPQ tier, PIM → CPQ pricing, WMS → PIM stock, PSP → CRM customer)
- Loose coupling via `orderId: uuid` where circular domain deps would otherwise arise (WMS and PSP reference orders by UUID rather than `ref<orders.Order>`)
- ODS read-optimised views materialised as `upsert` into PostgreSQL: `ProductAvailabilityView`, `TierPricingView`, `CustomerSalesView`, `OrderSupportView`, `LowStockAlertView`, `SalesRepWorkloadView`
- Separation of ODS (operational, minutes-lag, PostgreSQL) from data mart (analytical, ClickHouse) with distinct materialisation strategies per layer
- Data mart with five distinct fact/snapshot patterns: `append` (sales, logistics), `snapshot` (inventory, customer segments), `overwrite_partition` (pricing effectiveness)
- HMAC pseudonymisation of customer PII before any data mart landing
- RFM scoring and churn-risk signal computed entirely in CEL within `CustomerValueSegmentFact`
- Price change audit as an append-only fact table (`PriceChangeAuditFact`) for regulatory traceability
- Multi-binding workspace: PostgreSQL ODS + ClickHouse mart + Redis checkout cache + Kafka CDC stream + S3 lake archive

Domains: `crm`, `iam`, `pim`, `cpq`, `wms`, `psp`, `orders`, `ods`, `datamart`

---

### 8. Distributed Multi-Registry (`scenarios/08-distributed-multi-registry/`)

A federation of three independent teams (customer platform, orders platform, analytics) each maintain their own Modelable registry in separate git repositories. The analytics team consumes models from both upstream platforms via `import domain` declarations, pins versions with content signatures, and writes back consumer entries via automated PRs.

Key techniques demonstrated:
- `registry` and `peers` blocks in `workspace.mdl`
- `import domain … from registry "…"` with `#`-pinned version references
- Content signature verification (`modelable lineage verify`)
- Consumer write-backs as pull requests (`writeback: pr`)
- Registry DAG visualization (`modelable registry graph`)

See the [compiler reference](../docs/compiler-reference.md) for federation and lineage behavior.

---

### 9. Auto Projections (`scenarios/09-auto-projections/`)

A simple domain demonstrates the four compiler-generated projections (`db`, `request`, `reply`, `event`) for an `Order` entity, including inline customization with `exclude` and `on` filters.

Key techniques demonstrated:
- `auto projections Order @ 1 { db, request, reply, event }`
- `Product @ 2` is authored as an `evolves @ 1 { add brand?: string }`
  delta instead of repeating the complete field list, per [Language
  reference](../docs/language-reference.md) §2.7
- Versioned auto projections preserve `ProductReply@1` while publishing a
  compatible `ProductReply@2` for a new field.
- `pick(alias.field, ...)` creates an explicit, version-pinned public
  projection from the newer reply contract.
- `exclude` with field names and annotation filters (`@pii`, `@server`)
- `on` with operation subsets (`created`, `updated`, `deleted`)
- Inspecting expanded projections with `modelable inspect Order@1 --auto`

See the [language reference](../docs/language-reference.md) §3.7 and
[architecture](../docs/architecture.md) §3.5 for the full auto-projection rules.

---

### 10. Breaking-Change Impact Analysis (`scenarios/10-impact-analysis/`)

A minimal `customer` domain removes a field between versions, authored as an
`evolves` delta, and two downstream projections in separate domains react
differently: one uses the removed field and breaks, the other doesn't and
only needs regeneration.

Key techniques demonstrated:
- `entity Customer @ 2 (breaking) evolves @ 1 { remove email }` — an
  intentional breaking removal authored as a concise delta instead of a
  full field list, per [Language reference](../docs/language-reference.md) §2.7
- `modelable impact --from customer.Customer@1 --to customer.Customer@2`
  reports `billing.BillingCustomer` as breaking (it maps the removed
  `email` field) and `shipping.ShippingLabel` as needing regeneration only
  (it never referenced `email`) — the same source change, two different
  downstream consequences, both explicit rather than inferred

---

### 11. Fleet Telemetry Type System (`scenarios/11-fleet-telemetry-type-system/`)

A device-fleet domain (`fleet`) and its telemetry stream (`telemetry`) exist purely to exercise the newer additions to the type system: semantic type aliases, index declarations, timestamp-ordered UUIDs, fixed-width integers, fixed-length binary, and Protobuf field reservations, all in one small, realistic pair of domains.

Key techniques demonstrated:
- `semantic TenantId: uuid { registry: true }` — a registry-backed semantic type, allocated a stable id in `registry-ids.lock`
- `semantic FirmwareVersion: RawVersionString` — a semantic type chained onto another semantic type
- A domain-qualified semantic type reference (`fleet.TenantId`, `fleet.FirmwareVersion`) used from a different domain (`telemetry`)
- `uuid(7)` timestamp-ordered identifiers for both the `Device` entity key and the high-volume `TelemetryReading` event stream
- `binary(6)` (a MAC address) and `binary(32)` (a SHA-256 payload digest) fixed-length fields
- Fixed-width integers (`u8`, `u16`/`i16` via a semantic alias, `u32`) sized to their actual value ranges
- `index Device @ 1 { primary …; secondary … }` with a `unique` lookup index and a `sort`-ordered secondary index, compiled to real `CREATE INDEX`/`CREATE UNIQUE INDEX` statements by the Postgres SQL emitter
- `reserved protobuf { numbers: […]; names: […] }` reserving a retired field for wire compatibility
- `auto projections` combined with the above on the same entity

See the [language reference](../docs/language-reference.md) §2.1 (built-in types), §3.8 (semantic types), and §3.9 (index declarations).

---

## File Structure

Each scenario is organized by domain, with a `workspace.mdl` file defining global configuration:

```
scenarios/01-ecommerce-data-warehouse/
  ├── workspace.mdl      # Workspace configuration
  ├── customer.mdl       # Customer domain & models
  ├── commerce.mdl       # Commerce domain & models
  ├── payments.mdl       # Payments domain & models
  ├── analytics.mdl      # Analytics domain & projections
  └── bindings.mdl       # Adapter bindings

scenarios/07-multi-system-master-data/
  ├── workspace.mdl      # Workspace configuration & generation targets
  ├── crm.mdl            # Customer & Account master (source of truth for identity)
  ├── iam.mdl            # Internal User master (employees, roles, org hierarchy)
  ├── pim.mdl            # Product master (catalogue, variants, physical attributes)
  ├── cpq.mdl            # Pricing master (tiers, price lists, discount rules)
  ├── wms.mdl            # Logistics master (warehouses, stock levels, shipments)
  ├── psp.mdl            # Payment master (instruments, transactions, refunds)
  ├── orders.mdl         # Thin shared order domain (joins all six masters)
  ├── ods.mdl            # ODS read-optimised views (PostgreSQL, near-real-time)
  ├── datamart.mdl       # Analytics facts & snapshots (ClickHouse data mart/lake)
  └── bindings.mdl       # PostgreSQL ODS + ClickHouse mart + Redis + Kafka + S3
```

## Using with the CLI

```bash
# Validate a specific scenario
modelable validate scenarios/01-ecommerce-data-warehouse/

# Compile and generate artifacts
modelable compile scenarios/01-ecommerce-data-warehouse/ --target typescript --out ./dist/
```

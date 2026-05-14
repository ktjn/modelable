# Sample Scenarios

This directory contains six complete sample scenarios — one for each Modellable platform type. Each scenario is now defined using the canonical **Modellable IDL (`.mdl`)** format, demonstrating production-realistic definitions across multiple domains.

Use these as a starting point for your own definitions or validate them with the CLI (`modellable validate scenarios/<id>/`).

---

## Scenario Index

| # | ID | Title | Platform | Complexity |
|---|:---|:------|:---------|:-----------|
| 1 | `01-ecommerce-data-warehouse` | E-commerce Analytics Data Warehouse | Data Warehouse | High |
| 2 | `02-realtime-fraud-detection` | Real-Time Fraud Detection Service | High-Performance Service | High |
| 3 | `03-order-saga-microservices` | Order Fulfillment Saga | Event-Driven Microservices | High |
| 4 | `04-credit-risk-feature-store` | Credit Risk ML Feature Store | ML Feature Store | High |
| 5 | `05-partner-marketplace-api` | Partner Marketplace API | API Consumer | High |
| 6 | `06-gdpr-compliance-audit` | GDPR Compliance and Immutable Audit Trail | Audit & Compliance | High |

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

Domains: `ml-credit-risk`, `customer`, `lending`, `credit-bureau`

---

### 5. Partner Marketplace API (`scenarios/05-partner-marketplace-api/`)

A marketplace exposes catalog, inventory, and order data to 500+ seller partners through versioned projections. Modellable generates OpenAPI 3.1, TypeScript, and Protobuf artifacts directly from projection definitions. Per-seller access is enforced via runtime CEL filter parameters.

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
```

## Using with the CLI

```bash
# Validate a specific scenario
modellable validate scenarios/01-ecommerce-data-warehouse/

# Compile and generate artifacts
modellable compile scenarios/01-ecommerce-data-warehouse/ --target typescript --out ./dist/
```

> **Legacy YAML:** The original YAML definitions have been moved to `scenarios/legacy/` for historical reference.



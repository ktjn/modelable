# Sample Scenarios

This directory contains six complete sample scenarios — one for each Modellable platform type. Each scenario demonstrates complex, production-realistic definitions across multiple domains, showing how domains, models, projections, and adapter bindings compose together.

Use these as a starting point for your own definitions or load them interactively with the CLI (`modellable scenario load <id>`).

---

## Scenario Index

| # | ID | Title | Platform | Complexity |
|---|:---|:------|:---------|:-----------|
| 1 | `ecommerce-data-warehouse` | E-commerce Analytics Data Warehouse | Data Warehouse | High |
| 2 | `realtime-fraud-detection` | Real-Time Fraud Detection Service | High-Performance Service | High |
| 3 | `order-saga-microservices` | Order Fulfillment Saga | Event-Driven Microservices | High |
| 4 | `credit-risk-feature-store` | Credit Risk ML Feature Store | ML Feature Store | High |
| 5 | `partner-marketplace-api` | Partner Marketplace API | API Consumer | High |
| 6 | `gdpr-compliance-audit` | GDPR Compliance and Immutable Audit Trail | Audit & Compliance | High |

---

## Scenario Summaries

### 1. E-commerce Data Warehouse (`01-ecommerce-data-warehouse.yaml`)

A high-traffic marketplace feeds a ClickHouse analytics warehouse with customer lifetime value, acquisition-cohort revenue curves, checkout-funnel conversion rates, and multi-touch campaign attribution.

Key techniques demonstrated:
- Cross-domain joins across `customer`, `commerce`, and `payments`
- HMAC pseudonymisation of PII (email) before warehouse landing
- Append-only funnel facts preserving historical trajectory
- Pre-aggregated nightly cohort summaries (`overwrite_partition` strategy)
- `SummingMergeTree` and `ReplacingMergeTree` engine bindings for ClickHouse

Domains: `customer`, `commerce`, `payments`, `analytics`
Models: `Customer`, `Order`, `OrderLineItem`, `PaymentTransaction`
Projections: `CustomerLifetimeValue`, `OrderFunnelFacts`, `DailyCohortRevenue`, `ProductRevenueAttribution`

---

### 2. Real-Time Fraud Detection (`02-realtime-fraud-detection.yaml`)

A payment processor requires sub-millisecond fraud signal reads during payment authorisation. Four source models from different domains are denormalised into a single Redis hash per customer, refreshed continuously via Kafka.

Key techniques demonstrated:
- Denormalized multi-source join collapsed into one Redis key for zero-latency lookup
- CEL computed fields for derived risk signals (`velocityDeclineRatio1h`, `isMultiAccountDevice`)
- Separate per-merchant and per-device projections with independent TTLs
- `msgpack` serialisation for space-efficient Redis storage
- TTL-based data freshness guarantees (86400s customer, 3600s merchant)

Domains: `fraud`, `risk`, `payments`
Models: `CustomerRiskProfile`, `TransactionVelocity`, `MerchantRiskScore`, `DeviceFingerprint`
Projections: `CustomerFraudCheckSignals`, `MerchantFraudLookup`, `DeviceTrustProfile`

---

### 3. Order Fulfillment Saga (`03-order-saga-microservices.yaml`)

A five-service order fulfillment system coordinates via Kafka choreography. Each service subscribes to a filtered projection of domain events from the previous saga step. No service calls another directly.

Key techniques demonstrated:
- Field-scoped projections per consuming service (inventory never sees payment data)
- CEL filter expressions routing only operationally relevant events to each service
- Cross-domain join inside a projection (shipping service needs both payment and order data)
- Per-service dead-letter topics and configurable retry backoff
- Correlation key (`orderId`) propagated across all five event types
- `enableIdempotentProducer` and `acks: all` for exactly-once-at-Kafka semantics

Domains: `commerce`, `inventory`, `payments`, `shipping`, `notifications`
Models: `OrderCreated`, `InventoryReservation`, `PaymentAuthorisation`, `ShipmentLabel`, `OrderFulfillmentState`
Projections: `OrderReservationTriggers`, `ConfirmedInventoryEvents`, `CapturedPaymentEvents`, `FulfillmentNotificationTriggers`

---

### 4. Credit Risk ML Feature Store (`04-credit-risk-feature-store.yaml`)

A lending platform's ML team trains and serves a credit scoring model with point-in-time correct features. The same projection version drives both the offline training snapshot (Parquet on S3) and the online Redis serving layer, preventing training/serving skew.

Key techniques demonstrated:
- PIT-correct `pitCutoff` joins preventing future data leakage into training sets
- Three-tier PII handling: raw (internal ML platform), sensitive (annotated), anonymised (export)
- Bureau data bucketing (`credit_score_band`, `utilization_band`) to prevent re-identification
- Offline `snapshot` materialisation with `snapshotAt` template parameter
- Online `upsert` materialisation with Kafka subscription and lag alerting
- Feature staleness indicator (`bureau_report_age_days`)

Domains: `ml-credit-risk`, `customer`, `lending`, `credit-bureau`
Models: `CustomerFinancials`, `LoanApplication`, `LoanPaymentHistory`, `BureauReport`, `RiskScoreLabel`
Projections: `CreditFeaturesOffline`, `CreditFeaturesOnline`, `BureauFeaturesAnonymised`

---

### 5. Partner Marketplace API (`05-partner-marketplace-api.yaml`)

A marketplace exposes catalog, inventory, and order data to 500+ seller partners through versioned projections. Modellable generates OpenAPI 3.1, TypeScript, and Protobuf artifacts directly from projection definitions. Per-seller access is enforced via runtime CEL filter parameters.

Key techniques demonstrated:
- Internal-only fields (`supplierCostCents`, `marginCode`) explicitly absent from external projections
- Runtime auth-context filter parameters (`request.sellerId`) for row-level access control
- Artifact generation configuration (`openapi_3_1`, `typescript`, `protobuf`) per projection
- Webhook delivery with HMAC-SHA256 per-partner signing
- Graduated rate limiting per access scope (`catalogue.read` vs `orders.read`)
- `accessControlField` declaration for API gateway integration

Domains: `catalogue`, `inventory`, `commerce`, `marketplace-api`
Models: `ProductListing`, `ProductCategory`, `SellerInventoryLevel`, `SellerOrder`
Projections: `PartnerProductCatalogV2`, `SellerInventoryView`, `SellerOrderStatusV1`, `InventoryChangeWebhook`

---

### 6. GDPR Compliance and Audit Trail (`06-gdpr-compliance-audit.yaml`)

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
Models: `Customer`, `DataProcessingConsent`, `BillingTransaction`, `ErasureRequest`, `DataAccessEvent`
Projections: `GdprDataSubjectExport`, `ConsentHistory`, `BillingAuditTrail`, `ErasureTombstone`, `SensitiveDataAccessLog`

---

## File Format

> **Note:** These scenario files are legacy YAML examples created before the Modellable IDL was designed. They will be migrated to `.mdl` format as part of the Phase 1 implementation. The canonical file format going forward is `.mdl` — see the [IDL design spec](../docs/superpowers/specs/2026-05-14-modellable-idl-design.md) and the [CLI spec](../docs/specs/cli-spec.md#4-file-format) for details.

The new `.mdl` format uses brace-delimited blocks, `@decorator` annotations, and explicit lineage operators:

```mdl
domain customer {
  owner: "customer-platform"

  entity Customer @ 2 (additive) {
    @key   customerId: uuid
           legalName:  string
    @pii   email?:     string
  }
}

domain billing {
  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
  {
    billingCustomerId <- c.customerId
    name             <- c.legalName
    isBillable        = c.status == "active"
  }
}
```

## Using with the CLI

```bash
# Install the CLI
pip install -e cli/

# Validate .mdl definitions
modellable validate ./my-project/

# Ask an LLM to explain definitions
modellable describe ./my-project/

# Generate new definitions from a natural language description
modellable generate --output ./my-project/NewModel.mdl

# Inspect lineage
modellable lineage billing.BillingCustomer@1 --path ./my-project

# Compile to JSON Schema and TypeScript
modellable compile ./my-project --target json-schema --out ./dist/jsonschema
modellable compile ./my-project --target typescript --out ./dist/types
```

## Adapting a Scenario

1. Use `modellable generate` with a description of your use case to create a starting `.mdl` file
2. Edit the domain, model, and projection definitions for your specific entities
3. Update binding configs with your actual infrastructure endpoints and credential secret names
4. Validate: `modellable validate ./my-defs/`
5. Use `modellable generate --context ./my-defs/` to add new projections with LLM assistance

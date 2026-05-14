# External Tools to Incorporate for Modellable Data Modelling

## Goal

Focus Modellable on logical data modelling first.

Use external tools for validation, schema generation, artifact storage, catalog integration, generated types, documentation, and interoperability.

Do not incorporate runtime/materialisation tools yet.

---

## Recommended Boundary

Modellable should own:

- DSL
- normalized model graph
- semantic validation
- projection resolution
- compatibility checks
- lineage calculation
- classification propagation

External tools should own:

- schema validation libraries
- artifact registry
- catalog/governance UI
- generated language types
- data contract interchange
- downstream quality/runtime integrations

```text
Modellable DSL
   |
   v
Parser + Semantic Validator
   |
   v
Normalized Model Graph
   |
   |-- JSON Schema
   |-- Markdown docs
   |-- TypeScript types
   |-- OpenMetadata metadata
   |-- ODCS export
   `-- Registry artifacts
```

---

# Tool Stack

## 1. JSON Schema

### Use For

- Generated schema format
- Validating logical object models
- Consumer-facing contract format
- OpenAPI 3.1 compatibility
- Registry storage through Apicurio later

### Why

JSON Schema is the best first target because it is:

- language-neutral
- mature
- easy to validate locally
- compatible with OpenAPI 3.1
- supported by many registries and code generators

### Modellable Mapping

```text
Modellable Model       -> JSON Schema object
Modellable Projection  -> JSON Schema object
Field type             -> JSON Schema type/format
classification         -> x-modellable-classification
lineage                -> x-modellable-lineage
model reference        -> $ref or x-modellable-ref
```

### Example

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "modellable://customer/Customer/v1",
  "title": "customer.Customer.v1",
  "type": "object",
  "required": ["customerId", "email"],
  "properties": {
    "customerId": {
      "type": "string",
      "format": "uuid",
      "x-modellable-field": "customer.Customer.v1.customerId"
    },
    "email": {
      "type": "string",
      "x-modellable-classification": "pii",
      "x-modellable-field": "customer.Customer.v1.email"
    }
  },
  "x-modellable": {
    "kind": "Model",
    "domain": "customer",
    "name": "Customer",
    "version": 1
  }
}
```

### Recommendation

Use JSON Schema as the first generated contract format.

Do not make JSON Schema the internal DSL. Use it as output.

---

## 2. JSON Schema Tooling

### Python Libraries

Use:

```text
jsonschema
referencing
pydantic
ruamel.yaml
```

### Use For

- validating Modellable document shape
- validating generated JSON Schema
- resolving `$ref`
- implementing CLI validation
- strongly typed internal parser models

### Boundary

Use `pydantic` for internal implementation models.

Do not expose Pydantic as the contract model.

### Suggested Internal Flow

```text
YAML
  -> pydantic parser model
  -> semantic validation
  -> normalized graph
  -> JSON Schema output
  -> jsonschema validation
```

---

## 3. TypeScript Type Generation

### Tools

Use one of:

```text
json-schema-to-typescript
quicktype
```

### Use For

- frontend and Node.js consumers
- SDK generation
- typed projection consumers
- contract tests

### Mapping

```text
Modellable Model
  -> JSON Schema
  -> TypeScript interface/type
```

### Example Command

```bash
json2ts -i dist/jsonschema/customer.Customer.v1.schema.json -o dist/types/customer.Customer.v1.ts
```

### Recommendation

Delegate TypeScript generation to existing tools.

Do not write a custom TypeScript generator unless necessary.

---

## 4. Apicurio Registry

### Use For

- storing generated artifacts
- versioning generated schemas
- registry API
- compatibility checks later
- artifact lifecycle states

### Good Fit For

- JSON Schema
- Avro
- Protobuf
- OpenAPI
- AsyncAPI
- GraphQL

### Modellable Mapping

```text
customer.Customer.v1             -> Apicurio JSON Schema artifact
billing.BillingCustomer.v1        -> Apicurio JSON Schema artifact
partner.ProductListingApi.v1      -> Apicurio OpenAPI artifact
commerce.OrderEvents.v1           -> Apicurio AsyncAPI/Avro artifact
```

### Suggested Artifact IDs

```text
<domain>.<name>.v<version>
```

Examples:

```text
customer.Customer.v1
billing.BillingCustomer.v1
commerce.OrderPlaced.v3
```

### CLI Commands

```bash
modellable compile ./models --target json-schema --out ./dist/jsonschema
modellable publish apicurio ./dist/jsonschema
```

### Boundary

Use Apicurio as an artifact registry.

Do not use Apicurio as the Modellable source of truth.

---

## 5. OpenMetadata

### Use For

- catalog UI
- ownership
- stewardship
- glossary terms
- classification tags
- lineage visualization
- search/discovery
- data product browsing

### Modellable Mapping

```text
Modellable Domain      -> OpenMetadata Domain
Modellable Model       -> OpenMetadata custom asset or table-like asset
Modellable Projection  -> OpenMetadata data product or custom asset
Field classification   -> Tags / Glossary terms
Ownership              -> Owner / Steward
Lineage                -> Lineage edges
```

### Export Shape

```json
{
  "domains": [
    {
      "name": "customer",
      "owner": "customer-platform"
    }
  ],
  "assets": [
    {
      "name": "customer.Customer.v1",
      "type": "model",
      "domain": "customer",
      "fields": [
        {
          "name": "email",
          "classification": "pii"
        }
      ]
    }
  ],
  "lineage": [
    {
      "from": "customer.Customer.v1.email",
      "to": "billing.BillingCustomer.v1.invoiceEmail"
    }
  ]
}
```

### CLI Commands

```bash
modellable export openmetadata ./models --out ./dist/openmetadata.json
modellable publish openmetadata ./dist/openmetadata.json
```

### Boundary

Use OpenMetadata for visibility and governance workflows.

Do not make OpenMetadata the projection resolver.

---

## 6. Open Data Contract Standard / Data Contract CLI

### Use For

- interoperability
- exporting data-contract-style documents
- CI validation
- compatibility with existing data contract tooling
- external-facing contract exchange

### Modellable Mapping

```text
Modellable Model       -> ODCS data contract schema
Modellable Projection  -> ODCS dataset/data product contract
field classification   -> ODCS classification/custom property
quality constraints    -> ODCS quality section
owner                  -> ODCS owner
```

### Example Commands

```bash
modellable export odcs customer.Customer.v1 --out ./dist/customer.contract.yaml
datacontract lint ./dist/customer.contract.yaml
```

### Boundary

Use ODCS as an export/interchange format.

Do not force Modellable's internal model into ODCS if projections and lineage do not map cleanly.

---

## 7. Markdown Documentation Generator

### Use For

- human-readable model docs
- PR reviews
- architecture docs
- onboarding
- static site generation

### Tools

No heavy dependency needed.

Generate Markdown directly.

Optional publishing targets:

```text
MkDocs
Docusaurus
Backstage TechDocs
GitHub Pages
```

### Example Output

```md
# customer.Customer.v1

## Fields

| Field | Type | Required | Classification | Description |
|---|---|---:|---|---|
| customerId | uuid | yes | internal | Customer identity |
| email | string | yes | pii | Primary email address |

## Lineage

No upstream lineage. Canonical model.
```

### Recommendation

Add this early. It makes PR review much easier.

---

## 8. Avro

### Use Later For

- event schemas
- Kafka contracts
- schema evolution checks
- data pipeline contracts

### Modellable Mapping

```text
Model/Event      -> Avro record
Field            -> Avro field
Enum             -> Avro enum
Classification   -> custom Avro property
Lineage          -> custom Avro property
```

### Caveat

Avro has stricter type semantics than JSON Schema.

Do not let Avro drive the Modellable DSL too early.

---

## 9. Protobuf + Buf

### Use Later For

- gRPC APIs
- event contracts
- binary wire format
- breaking-change checks
- SDK generation

### Tools

```text
buf
protoc
```

### Modellable Mapping

```text
Model/Projection -> .proto message
Domain           -> package namespace
Version          -> package or message version
Field            -> message field
```

### Caveat

Protobuf requires stable numeric field tags.

If Protobuf becomes a target, Modellable must store field IDs.

Example:

```yaml
fields:
  customerId:
    type: uuid
    fieldId: 1
  email:
    type: string
    fieldId: 2
```

Do not add this until Protobuf is a committed target.

---

## 10. OpenAPI

### Use Later For

- API contract generation
- partner-facing schemas
- internal REST API schemas
- API gateway import

### Modellable Mapping

```text
Projection             -> OpenAPI schema
Projection collection  -> OpenAPI paths
Field                  -> schema property
Classification         -> x-modellable-classification
Lineage                -> x-modellable-lineage
```

### Caveat

OpenAPI needs API resource semantics, not just data model semantics.

Keep OpenAPI generation separate from the core model compiler.

---

## 11. AsyncAPI

### Use Later For

- event contract documentation
- stream topics
- publish/subscribe contracts
- Kafka/NATS/Pulsar integration

### Modellable Mapping

```text
Event model        -> AsyncAPI message
Domain stream      -> AsyncAPI channel
Schema             -> JSON Schema / Avro / Protobuf reference
```

### Caveat

AsyncAPI belongs in the event/runtime phase, not the first modelling phase.

---

# Recommended Incorporation Order

## Phase 1: Local Modelling Compiler

Incorporate:

```text
JSON Schema 2020-12
jsonschema
referencing
pydantic
ruamel.yaml
json-schema-to-typescript
Markdown generation
```

Build commands:

```bash
modellable validate ./models
modellable resolve customer.Customer.v1
modellable lineage billing.BillingCustomer.v1
modellable diff customer.Customer.v1 customer.Customer.v2
modellable compile customer.Customer.v1 --target json-schema
modellable compile customer.Customer.v1 --target typescript
modellable docs ./models --out ./dist/docs
```

## Phase 2: Artifact Registry

Incorporate:

```text
Apicurio Registry
```

Build commands:

```bash
modellable publish apicurio ./dist/jsonschema
modellable pull apicurio customer.Customer.v1
```

## Phase 3: Catalog / Governance Sync

Incorporate:

```text
OpenMetadata
```

Build commands:

```bash
modellable export openmetadata ./models --out ./dist/openmetadata.json
modellable publish openmetadata ./dist/openmetadata.json
```

## Phase 4: Contract Interchange

Incorporate:

```text
Open Data Contract Standard
Data Contract CLI
```

Build commands:

```bash
modellable export odcs customer.Customer.v1 --out ./dist/customer.contract.yaml
datacontract lint ./dist/customer.contract.yaml
```

## Phase 5: Runtime & Targets

Incorporate:

```text
Avro
Protobuf
Buf
OpenAPI
AsyncAPI
```

Build commands:

```bash
modellable compile commerce.OrderPlaced.v1 --target avro
modellable compile commerce.OrderPlaced.v1 --target protobuf
modellable compile partner.ProductListing.v1 --target openapi
modellable compile commerce.OrderEvents.v1 --target asyncapi
```

---

# Do Not Incorporate Yet

Avoid these during the data modelling phase:

```text
Kafka runtime provisioning
Redis materialisers
ClickHouse loaders
Feast integration
API gateways
Zilla
Confluent stream governance
dbt execution
Great Expectations execution
Soda execution
custom UI
custom registry
```

Reason:

These pull the design into runtime concerns before the logical model is stable.

---

# Recommended Default Stack

Use this as the first practical stack:

```text
Core implementation:
  Python
  pydantic
  ruamel.yaml
  jsonschema
  referencing

Generated artifacts:
  JSON Schema 2020-12
  Markdown
  TypeScript through json-schema-to-typescript

Registry:
  Apicurio later

Catalog:
  OpenMetadata later

Interchange:
  ODCS/Data Contract CLI later
```

---

# Final Recommendation

Start with:

1. JSON Schema as the first generated schema format.
2. jsonschema/referencing for validation.
3. json-schema-to-typescript for consumer types.
4. Markdown docs for reviewability.
5. Apicurio as the first external registry.
6. OpenMetadata as the first governance/catalog integration.
7. ODCS/Data Contract CLI as the first interoperability export.

Keep Modellable's core independent.

The critical asset is the normalized model/projection/lineage graph. Everything else should be generated from that graph.

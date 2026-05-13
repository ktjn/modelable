# Research: Data Model Languages for Modellable

This document evaluates existing data modeling languages and Domain-Specific Languages (DSLs) against the requirements of the Modellable platform.

## 1. Evaluation Criteria

Based on the [Modellable System Specification](../specs/modellable-system-spec.md), the chosen language(s) must support:

- **Platform-Neutral Definitions:** Decoupled from specific databases or brokers.
- **Explicit Derivation:** Ability to trace projected fields back to source fields.
- **Immutable Versioning:** Native support for schema versions and metadata.
- **Safe Expressions:** Deterministic, side-effect-free logic for computed fields.
- **Artifact Generation:** Capability to produce JSON Schema, TypeScript, SQL DDL, etc.

---

## 2. Candidate Languages by Category

### 2.1 API & Contract-First Modeling (Canonical Models)
These languages are designed to define the "Source of Truth" for system boundaries.

| Language | Developer | Strengths | Weaknesses |
| :--- | :--- | :--- | :--- |
| **Smithy** | AWS | Protocol-agnostic; rich "traits" for metadata (PII, deprecation). | Relational projection and join logic is not native. |
| **TypeSpec** | Microsoft | Excellent ergonomics (TS-like); strong OpenAPI/Protobuf output. | Focused more on API shapes than data transformation. |
| **LinkML** | LBNL/Loom | Semantic web roots; built-in support for "profiles" and subsets. | Complex tooling; YAML-heavy syntax. |

### 2.2 Semantic & Relational Transformation (Projections)
These languages handle how data is joined, filtered, and reshaped.

| Language | Strengths | Use Case in Modellable |
| :--- | :--- | :--- |
| **Malloy** | Understands relationships/joins; handles nested data naturally. | Modeling the "Semantic Layer" of cross-domain joins. |
| **PRQL** | Pipelined flow (`from` -> `filter` -> `select`); highly readable. | Defining the step-by-step logic of a projection. |
| **LinkML-Map** | Declarative YAML mappings for field-to-field transformations. | Explicit field derivation and unit conversions. |

### 2.3 Expression Languages (Computed Fields)
For logic that must be evaluated at runtime (e.g., `isBillable: status == 'active'`).

| Language | Strengths | Why for Modellable? |
| :--- | :--- | :--- |
| **CEL** | Fast, non-Turing complete, guaranteed termination, safe. | **Primary Choice.** Meets the spec's requirement for deterministic logic. |
| **JSONata** | Sophisticated JSON navigation and reshaping. | Alternative if complex structural reshaping is the priority. |
| **SpEL** | Deep JVM integration and power. | Risk of side effects; harder to sandbox for multi-platform use. |

---

## 3. Analysis for Modellable Requirements

### 3.1 Domain Ownership & Metadata
**Smithy** and **LinkML** excel here. Their ability to attach arbitrary "traits" or "annotations" to fields allows for first-class support for `classification: pii`, `owner: team-a`, and `replacedBy: field_v2`.

### 3.2 Explicit Derivation & Lineage
**LinkML-Map** is the only established tool that focuses on declarative "back-references." In most other languages, lineage must be inferred by parsing the code. Using a LinkML-inspired structure would make the "Registry" and "Lineage API" (Sections 7.1, 10) significantly easier to implement.

### 3.3 Platform Neutrality
**TypeSpec** and **Smithy** are the leaders in multi-target compilation. They treat the "logical model" as a distinct entity from the "wire format" (JSON/Proto) or "storage format" (SQL), which aligns perfectly with Modellable Section 2.3.

---

## 4. Recommendations

### Option A: The "Best-of-Breed" Hybrid (Recommended)
Build a custom YAML-based DSL that incorporates the best patterns from these languages:
1.  **Structure:** Use **Smithy/TypeSpec** concepts for shapes and metadata.
2.  **Transformations:** Use a **PRQL-inspired** pipeline syntax for projections.
3.  **Logic:** Embed **CEL** for all expression-based computed fields.

### Option B: The "LinkML-First" Path
Adopt **LinkML** as the core definition format.
- **Pros:** Standardized; handles both models and mappings; strong Python ecosystem.
- **Cons:** Might feel "academic" or overly verbose for standard application developers.

---

## 5. Implementation Stack

The custom YAML DSL is implemented in Python. The following libraries form the internal parser and validation layer.

| Library | Role |
| :--- | :--- |
| `ruamel.yaml` | Parse YAML DSL documents with round-trip fidelity. |
| `pydantic` | Strongly typed internal parser models (not the external contract). |
| `jsonschema` | Validate generated JSON Schema output and Modellable document shape. |
| `referencing` | Resolve `$ref` links within and across generated schemas. |

### Internal Compilation Flow

```
YAML DSL
  -> ruamel.yaml parse
  -> pydantic parser model
  -> semantic validation
  -> normalized model graph
  -> JSON Schema output
  -> jsonschema validation
```

`pydantic` models are used internally for type-safe graph construction. They are not exposed as the external contract format.

JSON Schema 2020-12 is the **first generated output target**. All other artifact formats (TypeScript, Avro, Protobuf, OpenAPI) are derived from or alongside JSON Schema.

### x-modellable Extensions in JSON Schema

Generated JSON Schema documents embed Modellable metadata using vendor extensions:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "modellable://customer/Customer/v1",
  "title": "customer.Customer.v1",
  "type": "object",
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

### TypeScript Type Generation

TypeScript types are generated from JSON Schema using `json-schema-to-typescript` (or `quicktype` as an alternative). Modellable does not write a custom TypeScript generator.

```bash
json2ts -i dist/jsonschema/customer.Customer.v1.schema.json -o dist/types/customer.Customer.v1.ts
```

---

## 6. Next Steps for Prototyping

1.  **Draft the Internal Schema:** Define how the "Registry" stores these definitions (JSON/Relational).
2.  **Prototype a CEL Validator:** Confirm that simple projection expressions can be validated against the source model schema.
3.  **Map PRQL to SQL/Streams:** Experiment with translating a pipelined projection into both a PostgreSQL `VIEW` and a Kafka transformation logic.
4.  **Implement JSON Schema export:** Generate a valid JSON Schema 2020-12 document from the normalized model graph, including `x-modellable` extensions.
5.  **Validate with jsonschema:** Run the generated schema through the `jsonschema` library to confirm structural correctness.
6.  **Integrate json-schema-to-typescript:** Confirm TypeScript types are generated correctly from the JSON Schema output.

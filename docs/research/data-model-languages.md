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

## 4. Decision

Three options were evaluated during design:

- **Option A — Custom YAML DSL:** Full control, but verbose for complex projection derivation logic and every emitter must be written from scratch.
- **Option B — Extend TypeSpec:** Gets OpenAPI/Protobuf emitters for free, but TypeSpec's API-centric model does not fit projection lineage and domain governance naturally.
- **Option C — Custom text IDL (chosen):** Purpose-built grammar in a text IDL (`.mdl` files). More expressive than YAML for derivation logic, LLM-friendly due to explicit delimiters and consistent structure, enables a language server.

**Chosen: Option C.** See `docs/superpowers/specs/2026-05-14-modellable-idl-design.md` for the full design rationale and syntax reference.

**Expression language for computed fields:** CEL (Common Expression Language). Deterministic, non-Turing-complete, sandboxable. Expressions are stored as raw strings in the IR and evaluated by the Phase 5 runtime. The compiler extracts field references from expressions for lineage tracking.

---

## 5. Implementation Stack

The Modellable IDL is implemented in Python. The following libraries form the internal parser and validation layer.

| Library | Role |
| :--- | :--- |
| `lark>=1.1` | Parse `.mdl` IDL files using an EBNF grammar (Earley parser). |
| `pydantic>=2.0` | Strongly typed internal IR models (not the external contract format). |
| `jsonschema` | Validate generated JSON Schema output. |
| `referencing` | Resolve `$ref` links within and across generated schemas. |

### Internal Compilation Flow

```
.mdl IDL file
  -> Lark parser (Earley, EBNF grammar)
  -> parse tree
  -> Lark Transformer -> Pydantic IR
  -> semantic validation
  -> normalized model graph
  -> target emitters (JSON Schema, TypeScript, OpenAPI, Avro, SQL DDL, …)
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

## 6. Implementation Plan

The implementation plan for Phase 1 (parser, IR, validation, and CLI) is at `docs/superpowers/plans/2026-05-14-idl-parser-ir-validation.md`.

Planned implementation sequence:
1.  **Lark grammar** (`cli/src/modellable/grammar/modellable.lark`) — EBNF for domains, models, projections, generate blocks, bindings.
2.  **Pydantic IR** (`cli/src/modellable/parser/ir.py`) — typed model graph.
3.  **Lark Transformer** (`cli/src/modellable/parser/transformer.py`) — parse tree → IR.
4.  **Semantic validation** (`cli/src/modellable/validation/semantic.py`) — enforce domain rules.
5.  **Compiler + CLI validate** — orchestration and `modellable validate` command.
6.  **Phase 1 emitters** — JSON Schema 2020-12, Markdown, TypeScript (separate plan).

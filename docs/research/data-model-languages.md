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

## 5. Next Steps for Prototyping

1.  **Draft the Internal Schema:** Define how the "Registry" stores these definitions (JSON/Relational).
2.  **Prototype a CEL Validator:** Confirm that simple projection expressions can be validated against the source model schema.
3.  **Map PRQL to SQL/Streams:** Experiment with translating a pipelined projection into both a PostgreSQL `VIEW` and a Kafka transformation logic.

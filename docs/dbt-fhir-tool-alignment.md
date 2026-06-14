# Research and Plan: Aligning with dbt, FHIR, and Other External Tools

> **Status:** Research and planning. No emitter, importer, or CLI work is
> committed by this document. It extends
> [external-tools-data-modelling.md](external-tools-data-modelling.md) and
> [migration-guide.md](migration-guide.md) with concept mappings and phased
> proposals for dbt, FHIR, and other ecosystems. Concrete work requires an
> issue and an accepted design per [ROADMAP.md](../ROADMAP.md).

## 1. Purpose

Teams adopting Modelable rarely start from a blank slate. Analytics teams
already run dbt; healthcare and life-sciences teams already exchange FHIR
resources; most organizations already have a catalog, lineage, or table-format
standard in place. This document maps Modelable's core concepts (domain,
model, model version, projection, lineage, classification) onto the concepts
of dbt and FHIR, proposes alignment work in phases consistent with the
existing roadmap, and surveys other tools worth evaluating.

Alignment here means two things, in priority order:

1. **Conceptual alignment** — using compatible terminology and version/derivation
   semantics so teams can map their existing dbt/FHIR artifacts onto `.mdl`
   without re-learning a new model of the world.
2. **Artifact alignment** — optional emitters/importers that generate or
   consume dbt and FHIR artifacts from the normalized Modelable graph.

Per [modelable-system-spec.md](modelable-system-spec.md) §2.6
(framework-first integration), Modelable should wrap and interoperate with
these tools, not replace or execute them.

## 2. dbt (data build tool)

### 2.1 Why dbt matters

dbt is the de facto standard for SQL-based transformation and documentation
in the analytics/warehouse layer. Domains that own canonical models in
Modelable frequently also own one or more dbt models that materialize those
models (or projections of them) into a warehouse. dbt's newer governance
features — model contracts, model versions, groups, access modifiers, and
exposures — cover much of the same ground as Modelable's model versions,
domain ownership, and projections, but scoped to the warehouse.

### 2.2 Concept mapping

| dbt concept | Modelable concept | Notes |
|---|---|---|
| `sources:` (raw, unmanaged tables) | External upstream not yet modeled, or a `binding` source | dbt sources describe data Modelable does not own; a Modelable domain may still declare a `binding` pointing at the same table once it has a canonical model |
| `models:` with `contract: {enforced: true}` | Published Model Version | Both are schema-enforced and intended to be stable contracts for downstream consumers |
| `versions:` / `latest_version` (dbt model versioning) | `Model @ N (additive\|breaking)` | Both express "this contract changed; old and new versions can coexist"; dbt expresses the diff per version, Modelable redeclares the full version |
| `columns:` with `name`, `data_type`, `constraints` | Field declarations with types and `@key`/constraints | Direct field-level mapping; dbt `data_type` is warehouse-specific and needs a type-mapping table similar to the existing JSON Schema mapping |
| `meta:` arbitrary key/value | `@classification(...)`, `@owner(...)`, custom annotations | dbt has no fixed governance vocabulary; Modelable's annotations are more structured |
| `group:` + `access: private\|protected\|public` | Domain ownership + projection visibility | dbt groups approximate domain ownership; `access` approximates "is this a published projection or an internal model" |
| `exposures:` (dashboards, applications, ML models that consume a model) | Projections / declared consumers | Both describe "who consumes this contract and how" |
| generic/singular `tests` | `constraints` on a Model Version | Both express validation rules attached to a schema |
| `semantic_models:` / `metrics:` (MetricFlow / dbt Semantic Layer) | No current equivalent | See §2.4 — potential future "metric" or aggregation-projection construct |
| `manifest.json` / `catalog.json` (dbt docs) | Normalized model graph / `modelable lineage` output | Both are machine-readable graphs of models, columns, and dependencies |

### 2.3 Alignment plan

**Phase A — dbt schema/source export (extends Phase 1/4 of
[external-tools-data-modelling.md](external-tools-data-modelling.md)):**

Add a `dbt-yaml` (working name) compile target that generates dbt
`schema.yml` fragments for a model or projection:

```bash
modelable compile customer.Customer@2 --target dbt-yaml --out ./dist/dbt
```

Generated output should map:

```text
Modelable Model/Projection -> dbt model/source entry
field name + type           -> column name + data_type (per-adapter type map)
@key                          -> constraints: [{type: primary_key}]
@pii / @classification        -> meta: {modelable_classification: ...}
owner                          -> meta: {modelable_owner: ...}
model version                  -> versions: [{v: N, ...}] or a versioned model name
lineage (projection)           -> meta: {modelable_lineage: [...]}
```

This lets a Modelable canonical model be dropped into an existing dbt project
as a documented, contract-enforced source or model stub without hand-writing
YAML.

**Phase B — dbt import (extends
[migration-guide.md](migration-guide.md) §3 source-format table):**

`modelable generate --from <dbt manifest.json | schema.yml> --output
models/<domain>.mdl` to bootstrap `.mdl` models from an existing dbt project,
following the same "review the generated output" workflow as other
LLM-assisted imports.

**Phase C — exposure/lineage stitching:**

Treat dbt `exposures` as external consumers in the lineage graph, so
`modelable lineage` can show "this field flows into dbt exposure X" even when
the exposure itself lives outside `.mdl`. This feeds
[distributed-lineage-spec.md](distributed-lineage-spec.md) rather than the
local compiler.

**Phase D — semantic layer (deferred, see §2.4).**

### 2.4 Open questions

- dbt model versioning expresses only the *diff* between versions
  (`versions: [{v: 1, columns: [...]}]` reusing a shared base); Modelable
  redeclares each version in full. The emitter should generate full
  per-version `columns:` blocks rather than attempt diff-based output —
  simpler and avoids inferring dbt's diff format from Modelable's diff engine.
- dbt `data_type` is adapter-specific (Snowflake vs. BigQuery vs. Postgres
  types differ). A `dbt-yaml` emitter needs either a single target-adapter
  type map (configurable) or to omit `data_type` and rely on `contract:
  {enforced: false}` for the initial pass.
- MetricFlow `semantic_models`/`metrics` have no Modelable equivalent today.
  Do not add a "metric" model kind speculatively; revisit only if a concrete
  consumer needs aggregation-as-contract beyond the existing `group by`
  projection aggregation (idl-design-spec.md §3.4).

## 3. FHIR (Fast Healthcare Interoperability Resources)

### 3.1 Why FHIR matters

FHIR (HL7) is the dominant interoperability standard for healthcare data
exchange. Any domain dealing with clinical or health-plan data will need its
canonical models to interoperate with FHIR Resources, Profiles, and
Extensions. FHIR's profiling mechanism — constraining or extending a base
Resource via a `StructureDefinition` with `derivation: constraint` — is
conceptually close to a Modelable projection that derives from a source model
with field-level lineage.

### 3.2 Concept mapping

| FHIR concept | Modelable concept | Notes |
|---|---|---|
| Resource (e.g., `Patient`, `Observation`, `Encounter`) | Canonical `entity`/`event` model | Base resources are externally owned canonical contracts, analogous to a model owned by an "HL7" domain |
| `StructureDefinition` (`derivation: specialization`) | Model Version schema | Defines fields (elements), cardinality, types, and terminology bindings |
| Profile (`StructureDefinition`, `derivation: constraint`, `baseDefinition: <url>`) | Projection deriving from a source model | A profile narrows cardinality/types and adds extensions on top of a base resource — same shape as `projection X from domain.Model@N as m { ... }` |
| Extension (`StructureDefinition`, `type: Extension`, stable `url`) | Additive optional field (`(additive)` version, `?` field) | FHIR extensions are versionless, stable-URL additive fields — close to Modelable's additive-change discipline |
| Canonical URL + `version` (business version) | `domain.Model@version` | Both are globally unique, versioned identifiers for a contract |
| `ValueSet` / `CodeSystem` + `binding.strength` | `enum(...)` (or `ref<Domain.CodeSet>` for shared vocabularies) | Controlled vocabularies; binding strength (`required`/`extensible`/`preferred`/`example`) has no direct Modelable equivalent today |
| `Reference(ResourceType)` | `ref<Domain.Model>` | Cross-resource/cross-domain reference |
| `meta.security` / `meta.tag` | `@classification(...)`, `@pii` | Security labels and classification tags |
| Implementation Guide (bundle of profiles + narrative + examples) | Workspace + generated Markdown docs | An IG is a versioned, documented bundle of profiles — analogous to a Modelable workspace's generated docs output |
| `CapabilityStatement` | Adapter binding capabilities | Declares what operations/resources a server supports |

### 3.3 Alignment plan

**Phase A — FHIR profile export (export-only, R4 first):**

Add a `fhir-profile` (working name) compile target that, given a Modelable
projection whose lineage traces to a declared FHIR base resource, generates a
FHIR R4 `StructureDefinition` with `derivation: constraint`:

```bash
modelable compile clinical.PatientSummary@1 --target fhir-profile --out ./dist/fhir
```

Mapping:

```text
Modelable Projection          -> StructureDefinition (derivation: constraint)
projection name + version      -> StructureDefinition.url + .version
baseDefinition                  -> declared via projection source annotation
field <- source.field           -> ElementDefinition with sliced/renamed path
enum(...)                        -> ElementDefinition.binding (valueSet, strength: required)
ref<Domain.Model>                -> ElementDefinition type Reference(ResourceType)
@pii / @classification            -> meta.security coding
```

Start with a small, explicitly supported set of base resources (e.g.
`Patient`, `Observation`, `Encounter`) rather than attempting full coverage of
the FHIR resource catalog.

**Phase B — terminology and reference mapping:**

- Map Modelable `enum(...)` to a FHIR `binding` (`valueSet` + `strength`).
  Modelable does not need its own ValueSet/CodeSystem resources initially —
  reference external canonical URLs.
- Map `ref<Domain.Model>` to FHIR `Reference(ResourceType)` when the target
  model corresponds to a known FHIR resource.

**Phase C — FHIR import (extends
[migration-guide.md](migration-guide.md) §3):**

`modelable generate --from <StructureDefinition.json> --output
models/<domain>.mdl` to draft a starting `.mdl` model/projection from an
existing profile, with the same human-review workflow as other imports.

**Phase D (Later, roadmap) — Implementation Guide packaging:**

Generate an IG-shaped documentation bundle (profiles + narrative + examples)
from a Modelable workspace, reusing the Markdown emitter.

### 3.4 Open questions / caveats

- FHIR's type system includes deeply nested `BackboneElement`s and recursive
  `Extension` structures, which are richer than Modelable's flat
  field/value-object model. Deep nesting should map to nested Modelable
  `value` models; very deep or recursive FHIR structures may not be fully
  representable and should fail with a clear `EMIT003`/`EMIT002`-style
  diagnostic (per [emitter-spec.md](emitter-spec.md) §10) rather than partial
  output.
- FHIR has multiple concurrently active versions (R4, R4B, R5, and R6 in
  ballot). An emitter must target one FHIR version explicitly. **Recommend
  R4** as the first target — it remains the most widely deployed version in
  production health systems.
- This is export/import of static profile artifacts only. FHIR servers (e.g.
  HAPI FHIR), `CapabilityStatement`-driven runtime conformance, and FHIR
  Subscriptions are runtime concerns and stay out of scope, consistent with
  the Phase 5 boundary in
  [external-tools-data-modelling.md](external-tools-data-modelling.md) and
  [technology-evaluation.md](technology-evaluation.md).

## 4. Other tools to evaluate for alignment

| Tool / standard | What it is | Why relevant to Modelable | Suggested alignment | Phase |
|---|---|---|---|---|
| **OpenLineage** | Open standard for lineage events (job/run/dataset/column facets); adopted by Airflow, Spark, dbt, OpenMetadata, and major cloud catalogs | Modelable's internal lineage graph could be exported as OpenLineage `ColumnLineageDatasetFacet` events, letting catalogs that already consume OpenLineage ingest Modelable lineage without a bespoke integration | Add an OpenLineage export alongside the planned OpenMetadata export (Phase 3) | 3 |
| **Open Data Contract Standard (ODCS) / Data Contract CLI** | Vendor-neutral data contract interchange format | Already on the roadmap (Phase 4); reaffirm — dbt model contracts and FHIR profiles both have partial overlap with ODCS fields (owner, classification, quality) | No change — keep as Phase 4 | 4 |
| **Apache Iceberg / Delta Lake (table formats)** | Open table formats with schema evolution (add/rename/widen columns with stable field IDs) | Schema evolution semantics (stable column IDs, additive-only safe changes) closely mirror Modelable's additive/breaking model and the field-ID concern already flagged for Protobuf | Potential `--target iceberg-schema` emitter reusing the same field-ID stability mechanism proposed for Protobuf | 5 |
| **Snowplow / Segment tracking plans** | Versioned event-schema governance for product analytics | "Event model + classification + versioning" maps closely to Modelable's `event` kind and `@classification` | Potential compile target for analytics/event-tracking teams | 5 |
| **OMOP CDM** | Common Data Model for healthcare observational research (alternative to FHIR for analytics use cases) | Worth a follow-up evaluation if FHIR's operational profile model proves too heavyweight for analytics-only healthcare domains | Evaluate only if a concrete healthcare-analytics consumer emerges; do not build speculatively | Later |
| **GraphQL SDL / federation (Apollo subgraphs)** | Schema definition language with subgraph ownership and composition | Subgraph ownership and composed schema concepts parallel Modelable domain ownership and cross-domain projections | Potential future compile target alongside OpenAPI (Phase 5) | 5 |

Tools already evaluated and not repeated here: JSON Schema, Avro, Protobuf,
OpenAPI, AsyncAPI, Apicurio, OpenMetadata, LinkML — see
[external-tools-data-modelling.md](external-tools-data-modelling.md) and
[data-model-languages.md](data-model-languages.md).

## 5. Recommended sequencing

This slots into the existing phased plan from
[external-tools-data-modelling.md](external-tools-data-modelling.md) and
[ROADMAP.md](../ROADMAP.md):

| Phase | Existing focus | New additions from this document |
|---|---|---|
| 1 — Local modelling compiler | JSON Schema, Markdown, TypeScript | none |
| 2 — Artifact registry | Apicurio | none |
| 3 — Catalog/governance sync | OpenMetadata | + OpenLineage export |
| 4 — Contract interchange | ODCS, Data Contract CLI | + dbt `schema.yml`/source export and import |
| 4b (new) — Domain-specific interchange | — | FHIR R4 profile export (small resource set) and import |
| 5 — Event/API/runtime targets | Avro, Protobuf, OpenAPI, AsyncAPI, runtime stack | + Iceberg/Delta schema target, analytics tracking-plan target, GraphQL SDL |

## 6. Non-goals

- Executing dbt, running a FHIR server, or collecting OpenLineage runtime
  events — these are runtime/execution concerns, consistent with
  [modelable-system-spec.md](modelable-system-spec.md) §2.6 and the "Do Not
  Incorporate Yet" list in
  [external-tools-data-modelling.md](external-tools-data-modelling.md).
- Redesigning the core `.mdl` type system or projection model to match dbt's
  or FHIR's type systems. All mapping happens in emitters/importers, not in
  the IDL or normalized graph.
- Adding a "metric"/semantic-layer model kind speculatively to mirror
  MetricFlow. Revisit only against a concrete requirement.

## 7. Open decisions

- Whether dbt and FHIR emitters/importers are first-party (in `cli/`) or
  third-party plugins, pending the plugin-registry decision already open in
  [emitter-spec.md](emitter-spec.md) §11.
- Which FHIR base resources are in scope for Phase 4b (proposed starting set:
  `Patient`, `Observation`, `Encounter`).
- Which warehouse dialect's `data_type` vocabulary the dbt emitter targets by
  default (or whether it omits `data_type` until `contract.enforced` is
  requested).

## 8. Dependencies

- [external-tools-data-modelling.md](external-tools-data-modelling.md) —
  phased external-tool roadmap this document extends
- [migration-guide.md](migration-guide.md) — import/source-format table this
  document extends
- [emitter-spec.md](emitter-spec.md) — emitter interface, diagnostics, and
  open decisions referenced for new targets
- [distributed-lineage-spec.md](distributed-lineage-spec.md) — cross-tool
  lineage stitching for dbt exposures and OpenLineage
- [ownership-permissions-spec.md](ownership-permissions-spec.md) —
  classification/ownership mapping for dbt `meta` and FHIR `meta.security`

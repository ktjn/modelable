# External Integrations and Tool Alignment

> **Status:** Research and planning. Most of this document's phased proposals
> (emitters, catalog/lineage integration, additional artifact targets) are not
> committed and require an issue and an accepted design per
> [ROADMAP.md](../ROADMAP.md). Shipped slices include `modelable attach`
> and `modelable spec` for dbt/FHIR/ODCS drift review,
> `modelable compile --target openlineage` for local lineage-event artifacts, and
> `modelable publish apicurio` /
> `modelable pull apicurio` for JSON Schema artifact registry workflows. This
> document consolidates earlier tool-boundary research and extends
> [getting-started.md](getting-started.md) with concept mappings and
> phased proposals for dbt, FHIR, and other ecosystems.

This document also consolidates the earlier external-tool boundary, technology
evaluation, and data-model-language survey. Those documents informed the
current choices but are not separate product specifications.

## Current Integration Boundary

Modelable owns the `.mdl` language, normalized graph, semantic validation,
projection resolution, compatibility, lineage, classification propagation, and
deterministic artifact generation. External systems may own artifact storage,
catalog UI, generated-code consumption, interchange, and runtime execution.

Current local outputs include JSON Schema, Markdown, TypeScript, C#, Java,
Python, Rust, Go, SQL DDL, dbt `schema.yml`, FHIR R4 profiles,
OpenMetadata JSON, and OpenLineage event JSON. `modelable attach` provides
one-off dbt/FHIR/ODCS drift review, `modelable spec` tracks local
dbt/FHIR/ODCS files in
`.modelable/specs.yml` for repeatable status/diff/sync workflows, and Apicurio
publish/pull provides the shipped live JSON Schema artifact-registry workflow.
Live catalog synchronization, remote tracked-spec polling, additional schema
targets, CDC, brokers, materializers, and API gateways remain deferred until
they have an issue and accepted design.

Earlier evaluations considered TypeSpec, Smithy, LinkML, CUE, dbt, Malloy,
GraphQL, JSON Schema, Apicurio, OpenMetadata, ODCS, Avro, Protobuf, OpenAPI,
AsyncAPI, Debezium, Kafka, Pulsar, NATS, Redis, ClickHouse, and related tools.
They are candidates, not dependencies or commitments. A future integration
must preserve Modelable's source-of-truth, ownership, immutability, lineage,
and platform-neutrality rules.

### Apicurio Registry

`modelable publish apicurio SOURCE --url URL [--group GROUP]` generates JSON
Schema 2020-12 artifacts from `SOURCE` and publishes them to Apicurio Registry
3.x Core Registry API v3. Artifact IDs use `domain.Name.vVersion`, and the
default Apicurio group is `default`.

`modelable pull apicurio REF --url URL [--group GROUP] [--out DIR]` retrieves a
JSON Schema artifact by Modelable reference (`domain.Name@version`) and writes
it locally as `DIR/domain/Name.vVersion.json`.

This integration stores and retrieves derived artifacts only. It does not make
Apicurio the source of truth for Modelable models, projections, compatibility,
lineage, governance findings, or access policy.

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

Per [architecture.md](architecture.md) §2.6
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

**Implemented — dbt schema/source export (extends Phase 1/4 of
the integration boundary above):**

`modelable compile --target dbt-yaml` generates dbt `schema.yml` fragments for
a model or projection:

```bash
modelable compile ./models --target dbt-yaml --out ./dist/dbt
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

**Implemented (first pass) — dbt import (extends
[getting-started.md](getting-started.md) source-format table):**

`modelable generate --from <dbt manifest.json | schema.yml> --output
models/<domain>.mdl` bootstraps `.mdl` models from local dbt models or source
tables, following the same "review the generated output" workflow as other
imports. Use `--name` to select a specific dbt model or source table when a
file contains multiple candidates.

**Implemented (partial):** `modelable attach <Domain.Model@version> --source
<schema.yml> --source-format dbt [--source-name NAME]` imports a dbt model's
`columns:` (with `data_type`, `constraints`, and `modelable_*` `meta` keys) and
compares them to an existing published model version, appending a new version
with a computed `additive`/`breaking` change kind when they differ. See
[cli-reference.md](cli-reference.md) §10.9.

`modelable spec add ... --kind dbt` records the same dbt source in
`.modelable/specs.yml` so `modelable spec status`, `spec diff`, and
`spec sync --preview|--write` can repeat the drift review without restating the
source path and binding.

**Phase C — exposure/lineage stitching:**

Treat dbt `exposures` as external consumers in the lineage graph, so
`modelable lineage` can show "this field flows into dbt exposure X" even when
the exposure itself lives outside `.mdl`. This feeds
[compiler-reference.md](compiler-reference.md) rather than the
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
  projection aggregation ([language-reference.md](language-reference.md) §3.4).

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

**Implemented export — FHIR profile artifacts (R4 first):**

`modelable compile --target fhir-profile` generates FHIR R4
`StructureDefinition` artifacts from Modelable projections:

```bash
modelable compile ./models --target fhir-profile --out ./dist/fhir
```

Mapping:

```text
Modelable Projection          -> StructureDefinition (derivation: constraint)
projection name + version      -> StructureDefinition.url + .version
baseDefinition                  -> declared via projection source annotation
field <- source.field           -> ElementDefinition with sliced/renamed path
enum(...)                        -> ElementDefinition.binding (valueSet, strength: required)
ref<Domain.Model>                -> ElementDefinition type Reference(ResourceType)
@pii / @classification            -> Modelable FHIR extensions
```

The first hardened base-resource set is `Patient`, `Observation`, and
`Encounter`. Projections whose source model name matches one of those resources
emit R4 `StructureDefinition` constraint profiles with deterministic root and
field `ElementDefinition` entries, source-field lineage mappings, primitive
type mappings, enum bindings to Modelable ValueSet URLs, FHIR `Reference`
target profiles, repeating field cardinality, and Modelable
classification/PII extensions. Other projection sources fall back to FHIR
`Basic` with an emitter warning rather than silently claiming unsupported
resource-specific conformance. Representative FHIR-native Patient profile
output is validated with the HL7-maintained Java FHIR Validator smoke in the
local/CI gate when `validator_cli.jar` is available.

**Phase B — terminology and reference mapping:**

- Map Modelable `enum(...)` to a FHIR `binding` (`valueSet` + `strength`).
  Modelable does not need its own ValueSet/CodeSystem resources initially —
  reference external canonical URLs.
- Map `ref<Domain.Model>` to FHIR `Reference(ResourceType)` when the target
  model corresponds to a known FHIR resource.

**Implemented (first pass) — FHIR import (extends
[getting-started.md](getting-started.md) source-format table):**

`modelable generate --from <StructureDefinition.json> --output
models/<domain>.mdl` drafts a starting `.mdl` model from an existing local
profile, with the same human-review workflow as other imports.

**Implemented (partial):** `modelable attach <Domain.Model@version> --source
<StructureDefinition.json> --source-format fhir` imports the direct child
elements of a FHIR R4 `StructureDefinition` (primitive types, `Reference`
targets, and cardinality) and compares them to an existing published model
version, appending a new version with a computed `additive`/`breaking` change
kind when they differ. Elements with complex FHIR types (e.g.
`BackboneElement`, `HumanName`, `CodeableConcept`) fall back to a named type
with a warning, per §3.4. See [cli-reference.md](cli-reference.md) §10.9.

`modelable spec add ... --kind fhir` makes the same static profile file
trackable for repeatable status/diff/sync workflows. ODCS YAML documents can
also bootstrap brand-new `.mdl` models through `modelable generate --from`
or an explicit `--format odcs`.

**Phase D (Later, roadmap) — Implementation Guide packaging:**

Generate an IG-shaped documentation bundle (profiles + narrative + examples)
from a Modelable workspace, reusing the Markdown emitter.

### 3.4 Open questions / caveats

- FHIR's type system includes deeply nested `BackboneElement`s and recursive
  `Extension` structures, which are richer than Modelable's flat
  field/value-object model. Deep nesting should map to nested Modelable
  `value` models; very deep or recursive FHIR structures may not be fully
  representable and should fail with a clear `EMIT003`/`EMIT002`-style
  diagnostic (per [compiler-reference.md](compiler-reference.md) §10) rather than partial
  output.
- FHIR has multiple concurrently active versions (R4, R4B, R5, and R6 in
  ballot). An emitter must target one FHIR version explicitly. **Recommend
  R4** as the first target — it remains the most widely deployed version in
  production health systems.
- This is export/import of static profile artifacts only. FHIR servers (e.g.
  HAPI FHIR), `CapabilityStatement`-driven runtime conformance, and FHIR
  Subscriptions are runtime concerns and stay out of scope, consistent with
  the Phase 5 boundary in
  the integration boundary and deferred-candidate summary above.

## 4. Other tools to evaluate for alignment

| Tool / standard | What it is | Why relevant to Modelable | Suggested alignment | Phase |
|---|---|---|---|---|
| **OpenLineage** | Open standard for lineage events (job/run/dataset/column facets); adopted by Airflow, Spark, dbt, OpenMetadata, and major cloud catalogs | Modelable's internal lineage graph can be exported as OpenLineage `ColumnLineageDatasetFacet` events, letting catalogs that already consume OpenLineage ingest Modelable lineage without a bespoke integration | Local `modelable compile --target openlineage` emits deterministic design-time events with schema and column-lineage facets; runtime event collection remains deferred | 3 |
| **Open Data Contract Standard (ODCS) / Data Contract CLI** | Vendor-neutral data contract interchange format | Already on the roadmap (Phase 4); reaffirm — dbt model contracts and FHIR profiles both have partial overlap with ODCS fields (owner, classification, quality) | Local ODCS import is implemented for `attach`/`spec`; `modelable compile --target odcs` exports ODCS v3.1.0 YAML for models and projections; Data Contract CLI lint validation is implemented in local and CI gates | 4 |
| **Apache Iceberg / Delta Lake (table formats)** | Open table formats with schema evolution (add/rename/widen columns with stable field IDs) | Schema evolution semantics (stable column IDs, additive-only safe changes) closely mirror Modelable's additive/breaking model and the field-ID concern already flagged for Protobuf | Potential `--target iceberg-schema` emitter reusing the same field-ID stability mechanism proposed for Protobuf | 5 |
| **Snowplow / Segment tracking plans** | Versioned event-schema governance for product analytics | "Event model + classification + versioning" maps closely to Modelable's `event` kind and `@classification` | Potential compile target for analytics/event-tracking teams | 5 |
| **OMOP CDM** | Common Data Model for healthcare observational research (alternative to FHIR for analytics use cases) | Worth a follow-up evaluation if FHIR's operational profile model proves too heavyweight for analytics-only healthcare domains | Evaluate only if a concrete healthcare-analytics consumer emerges; do not build speculatively | Later |
| **GraphQL SDL / federation (Apollo subgraphs)** | Schema definition language with subgraph ownership and composition | Subgraph ownership and composed schema concepts parallel Modelable domain ownership and cross-domain projections | Potential future compile target alongside OpenAPI (Phase 5) | 5 |

Tools already evaluated and not repeated here: JSON Schema, Avro, Protobuf,
OpenAPI, AsyncAPI, Apicurio, OpenMetadata, LinkML — see
the consolidated research summary above.

## 5. Recommended sequencing

This slots into the existing phased plan from
[the integration boundary](#current-integration-boundary) and
[ROADMAP.md](../ROADMAP.md):

| Phase | Existing focus | New additions from this document |
|---|---|---|
| 1 — Local modelling compiler | JSON Schema, Markdown, TypeScript | none |
| 2 — Artifact registry | Apicurio | none |
| 3 — Catalog/governance sync | OpenMetadata | + OpenLineage export |
| 4 — Contract interchange | ODCS, Data Contract CLI | dbt `schema.yml` export, dbt model/source-table import, dbt manifest model import, and ODCS local-file import/export are implemented; remote polling remains deferred |
| 4b (new) — Domain-specific interchange | — | FHIR R4 StructureDefinition export and local-file import are implemented; Patient/Observation/Encounter profile bases have hardened element mapping with representative cardinality coverage; representative HL7 FHIR Validator smoke is implemented; custom-field extension mapping and deeper conformance remain deferred |
| 5 — Event/API/runtime targets | Avro, Protobuf, OpenAPI, AsyncAPI, runtime stack | + Iceberg/Delta schema target, analytics tracking-plan target, GraphQL SDL |

## 6. Non-goals

- Executing dbt, running a FHIR server, or collecting OpenLineage runtime
  events — these are runtime/execution concerns, consistent with
  [architecture.md](architecture.md) §2.6 and the deferred
  Incorporate Yet" list in
  boundary in this document.
- Redesigning the core `.mdl` type system or projection model to match dbt's
  or FHIR's type systems. All mapping happens in emitters/importers, not in
  the IDL or normalized graph.
- Adding a "metric"/semantic-layer model kind speculatively to mirror
  MetricFlow. Revisit only against a concrete requirement.

## 7. Open decisions

- Whether future ecosystem targets remain first-party or move to third-party
  plugins, pending the plugin-registry decision already open in
  [compiler-reference.md](compiler-reference.md) §11.
- How Modelable-only fields should map into FHIR extensions or slices when
  they are not legal child elements of the selected base resource.
- Which warehouse dialect's `data_type` vocabulary the dbt emitter targets by
  default (or whether it omits `data_type` until `contract.enforced` is
  requested).

## 8. Dependencies

- [Getting started](getting-started.md) for migration and source-format guidance.
- [Compiler reference](compiler-reference.md) for emitters and graph export.
- [Language reference](language-reference.md) for classification and ownership.
- [Architecture](architecture.md) for product boundaries and deferred runtime scope.

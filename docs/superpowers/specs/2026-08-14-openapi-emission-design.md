# OpenAPI Emission (REST API Support) Design

Date: 2026-08-14

## 1. Purpose

"API support" in Modelable today means **grammar acceptance only**: `.mdl`
sources can declare `generate { openapi -> "./generated/api/" }` and the
compiler parses, validates, and canonically formats it, but nothing consumes
that declaration to produce an artifact
(`docs/language-reference.md` §4.3). The only working OpenAPI path is
**import**, and it is LLM-assisted, not deterministic
(`cli/src/modelable/llm/importers.py::_import_openapi`,
`docs/architecture.md` line 1207: "Avro, OpenAPI, and AsyncAPI generation
(Phase 5) — import-only support exists via LLM-assisted generators").

This document is an accepted design target for closing that gap: a
deterministic, compiler-owned `openapi` codegen target, plus hardening the
existing import path so round-tripping is possible. It is a design, not an
implementation plan — a plan should be written and reviewed separately once
this design is accepted, following the same split used for Protobuf/gRPC
(`docs/superpowers/specs/archived/2026-07-04-scalable-protobuf-grpc-support-design.md`
paired with `docs/superpowers/plans/archived/2026-07-04-protobuf-target-first-slice.md`).

## 2. Context

- `docs/compiler-reference.md` §2 lists `OpenAPI | 5 | Deferred`, alongside
  Avro and AsyncAPI.
- `docs/compiler-reference.md` §4 already states the intended shape in one
  line: "OpenAPI: generate schemas from projections, not necessarily
  canonical entities." This design expands that line into a concrete
  mapping.
- `ROADMAP.md` Priority 5 ("Format delivery sequence", item 1) names
  hardening OpenAPI import and adding OpenAPI export as **P0** — ahead of
  Avro, AsyncAPI, XSD, and GraphQL.
- `ROADMAP.md` Priority 6, Slice F2 ("OpenAPI emission") instead frames
  export as gated: "After D1-D4, C1 (shipped), and C3 (shipped). Do not
  treat grammar acceptance of `openapi` as implemented emitter support."
  D1 (presence/nullability), D2 (value constraints), D3 (named enums), and
  D4 (discriminated unions) are all listed as **not yet started**.
- These two roadmap statements are in tension: Priority 5 wants export now,
  Priority 6 says wait for four unstarted language slices. §5 below resolves
  this by splitting the work so the P0 slice does not actually depend on
  D1-D4 — it only needs the compiler surface that exists today (entities,
  projections, primitives, inline enums, arrays, maps, `ref<>`, optional
  fields). D1-D4 improve *fidelity* of an already-shipped emitter rather than
  gating its existence. This mirrors how Protobuf shipped first
  (`2026-07-04-protobuf-target-first-slice.md`) and then received fidelity
  follow-ups (schema fidelity, semantic identity, descriptor artifacts,
  compat/reservations) as separate, later plans.
- The auto-projection system (`docs/language-reference.md` §3.7) already
  produces exactly the shapes an API needs: `{Entity}Request` (write model,
  `@server` fields excluded), `{Entity}Reply` (read model), `{Entity}Db`
  (persistence, not API-facing), and `{Entity}Event` (change event). OpenAPI
  emission is primarily a mechanical translation of `request`/`reply`
  projections already present in the model graph, not a new modeling
  concept.
- Every existing emitter follows the same interface
  (`cli/src/modelable/emitters/base.py::EmittedArtifact`) and is registered
  in `cli/src/modelable/emitters/targets.py::CODEGEN_TARGETS`. `grpc.py`
  demonstrates the precedent this design reuses in §6: a second emitter
  layered on top of a first one's output (`emit_grpc` calls `emit_protobuf`
  and adds a service layer) rather than a monolithic emitter.

## 3. Design Principles

Carried over from the project's existing emitter principles
(`docs/compiler-reference.md` §1, and the Protobuf/gRPC design):

- `.mdl` remains the reviewed source of truth. Generated OpenAPI documents
  are build output, never hand-edited, never a second source of contract
  truth.
- Emitters are deterministic: same normalized graph and options produce
  byte-for-byte identical output.
- No silent information loss. Where the current type system cannot express
  an OpenAPI concept precisely (or vice versa on import), emit an explicit
  `type_loss`/lossy-import diagnostic (`emitters/diagnostics.py::type_loss`
  already used by the JSON Schema and FHIR emitters) instead of guessing.
- Reuse the existing JSON Schema emitter's type-mapping logic rather than
  re-deriving it — OpenAPI 3.1 schemas are JSON Schema 2020-12 compatible by
  design, and Modelable's JSON Schema emitter already solves the
  primitive/enum/array/map/`ref<>` mapping problem once
  (`cli/src/modelable/emitters/json_schema.py`).
- Path and operation shape must be as explicit and reviewable as Protobuf
  field numbers are ("Field numbers are part of the generated contract" —
  `2026-07-04-scalable-protobuf-grpc-support-design.md` §5). Inferring REST
  routes silently from naming conventions is rejected for the same reason
  Scalable's gRPC service shape was declared explicitly rather than derived
  — see §6.2.

## 4. Non-Goals

- No HTTP server or runtime request handling. Modelable stays a compiler;
  it does not become a web framework or API gateway.
- No authentication/authorization runtime enforcement. Security scheme
  *declaration* in the generated document is in scope (§6.3); enforcing it
  is an external tool's job, matching how OpenLineage/OpenMetadata export
  metadata without becoming the runtime.
- No live API-catalog publishing in this phase (parallel to "Live
  OpenMetadata catalog synchronization" staying deferred while local export
  ships).
- No change to the `entity`/`projection`/`auto projections` grammar in
  Phase A (§6.1). Phase B (§6.2) proposes new grammar and is explicitly
  gated on product demand, not bundled into this design's acceptance.

## 5. Scope and Phasing

Two independently shippable layers, matching the Protobuf/gRPC precedent of
schema-first, service-shape-second:

| Phase | Deliverable | Depends on |
|---|---|---|
| A | `openapi` target emits `components.schemas` (and a minimal valid document envelope) from `request`/`reply`/hand-authored API-facing projections | Nothing beyond what's implemented today |
| B | Path/operation generation (`paths`, HTTP verbs, status codes, error responses) | A, plus a new explicit route-declaration grammar (proposed §6.2) |
| C | Deterministic OpenAPI **import** hardening (currently LLM-assisted only) | Independent of A/B; reuses A's type-mapping tables in reverse |
| D | Fidelity follow-ups: constraints (D2), presence/nullability (D1), named enum reuse (D3), discriminated unions (D4) | Corresponding language slice ships |

Phase A alone already satisfies `docs/compiler-reference.md`'s stated scope
("generate schemas from projections") and unblocks the `generate { openapi
-> ... }` block to mean something. Phase B is where "API support" most
plausibly means what a user of that phrase expects (an actual REST
contract), and is the part requiring a real design decision — see §6.2.

## 6. Phase A — Schema-Only OpenAPI Target

### 6.1 CLI surface

```text
modelable compile ./models --target openapi --out ./dist/openapi
```

Registered in `emitters/targets.py`:

```python
CodegenTarget(
    name="openapi",
    description="OpenAPI 3.1 component schemas generated from API-facing projections",
    status="implemented",
    kind="artifact",
    default_out_dir=Path("./dist/openapi"),
),
```

Output: one `openapi.json` (or one per domain, mirroring the FHIR/ODCS
per-domain layout — an implementation-plan decision, not a design one) with:

```json
{
  "openapi": "3.1.0",
  "info": { "title": "<workspace name>", "version": "<workspace/document version>" },
  "components": {
    "schemas": { "...": "..." }
  },
  "paths": {}
}
```

`paths: {}` stays empty and present (a structurally valid, empty OpenAPI
document) until Phase B. This lets tooling that expects a complete document
(linters, `openapi-generator`, Redocly) consume Phase A output today for
client/schema generation even without operations.

### 6.2 What gets a schema

Not every model version is API-facing. Emit `components.schemas` entries
for:

- Every `request`/`reply` kind produced by `auto projections`
  (`{Entity}Request`, `{Entity}Reply`).
- Every hand-authored projection, unless explicitly excluded (see below) —
  this covers cross-domain projections like `BillingCustomer` that are
  legitimately API-facing even though they didn't come from `auto
  projections`.
- `{Entity}Event` schemas go under `components.schemas` too (useful for
  documenting webhook/event payloads even before Phase B adds an
  `openapi` webhooks section) but are tagged `x-modelable.kind: "event"`
  so tooling can filter them out of request/response contexts.

Not emitted by default:

- `{Entity}Db` projections (persistence contract, not API-facing — same
  exclusion logic the SQL DDL emitter's counterpart already assumes).
- Canonical `entity`/`aggregate` model versions themselves, unless a
  projection explicitly exposes them 1:1. This matches
  `docs/compiler-reference.md`'s "not necessarily canonical entities" note:
  the *shape* an API returns is a projection's job to decide, not the
  entity's.

A model or projection can opt out of OpenAPI emission entirely with a
`generate { }`-block-scoped exclusion, or opt a `db`-kind projection *in*,
for domains that intentionally expose persistence-shaped APIs. Exact syntax
is an implementation-plan detail; the requirement is that inclusion is
never silently automatic for `db` projections and never silently excluded
for `request`/`reply`/hand-authored projections.

### 6.3 Type mapping

Reuses `json_schema.py`'s existing mapping (`PrimitiveType`, `EnumType`,
`ArrayType`, `MapType`, `RefType`, `FixedBinaryType`, `DecimalType`,
`NamedType`, `ObjectType` from `parser/ir.py`) with OpenAPI-specific
adjustments:

| Modelable IR | OpenAPI 3.1 schema | Notes |
|---|---|---|
| `PrimitiveType` (string, int, float, bool, uuid, timestamp, date, bytes) | same table `json_schema.py` already uses (`string`/`format: uuid`, `date-time`, etc.) | No new mapping work; call the shared helper. |
| `EnumType` (inline `enum(a, b, c)`) | `{"type": "string", "enum": ["a","b","c"]}` inlined per use site | Without D3 (named enums), no shared `components.schemas` enum definition to `$ref` — each use site gets its own inline enum. Flagged as a fidelity gap closed by Phase D once D3 ships. |
| `ArrayType` | `{"type": "array", "items": ...}` | Direct. |
| `MapType` | `{"type": "object", "additionalProperties": ...}` | Direct, same as JSON Schema emitter. |
| `RefType` (`ref<Domain.Model @ version>`) | `{"$ref": "#/components/schemas/Domain.Model.vN"}` | Reuses the JSON Schema emitter's existing `$ref` resolution via `resolve_model_ref`. |
| `DecimalType` | `{"type": "string", "format": "decimal"}` or `x-modelable-decimal` extension | Matches the "precise numeric values" treatment already solved for Protobuf; OpenAPI/JSON have no native decimal type. |
| `FixedBinaryType` | `{"type": "string", "format": "byte"}` | Base64, standard OpenAPI convention. |
| field optional (`field?`) | omitted from `required` array | Without D1, no distinction between "absent" and "explicit null" — matches OpenAPI 3.0-era optionality exactly, which is a reasonable default fidelity, not a blocker. |
| `@server` field | excluded already at the `request` auto-projection level | No extra OpenAPI-side logic needed; the projection graph already did this. |

Constraint annotations (min/max, pattern, length) have no IR representation
yet (D2), so there is nothing to map — not a loss, just nothing to emit
until D2 lands.

### 6.4 Metadata and governance

Every emitted schema carries an `x-modelable` extension object, consistent
with every other Modelable emitter (`json_schema.py`, `odcs.py`,
`openmetadata.py`):

```json
"x-modelable": {
  "domain": "customer",
  "name": "CustomerReply",
  "kind": "reply",
  "sourceEntity": "customer.Customer@2",
  "version": 1,
  "changeKind": "additive"
},
"x-modelable-por": { "...": "..." }
```

`@pii`/`@classification` annotations propagate the same way the JSON Schema
emitter already propagates them (governance metadata belongs in the
extension object, not as a change to standard OpenAPI keywords — matches
FHIR's Modelable classification extensions).

### 6.5 Compatibility validation

`supports_compat_check` should stay `False` for `openapi` in Phase A. A
schema's compatibility is already fully governed by the underlying
projection's compatibility report (Slice C1/C3, both shipped) — there is no
OpenAPI-specific wire concern the way Protobuf field numbers are a
Protobuf-specific wire concern. `modelable validate-compat` continues to
answer "is this change safe" at the projection level; OpenAPI just reflects
that answer. This should be revisited once Phase B adds paths, where a
removed/renamed operation *is* an OpenAPI-specific breaking change
independent of schema compatibility.

## 7. Phase B — Paths and Operations (proposed, not accepted)

Schemas alone are not "API support" in the way most people mean it — a REST
contract needs routes, verbs, status codes, and request/response bindings.
Nothing in today's grammar declares any of that. Three options, in
increasing order of how much new grammar they require:

**Option 1 — pure convention, no grammar change.** Derive CRUD routes from
each entity with `auto projections`: `GET /{plural}`, `GET
/{plural}/{id}`, `POST /{plural}` (body: `{Entity}Request`, response:
`{Entity}Reply`), `PUT /{plural}/{id}`, `DELETE /{plural}/{id}`, using the
`@key` field as the path parameter and an English pluralizer for the
collection name. **Rejected** by §3's principle against inferring routes
silently: pluralization is lossy/ambiguous (compare Protobuf field numbers,
which are never inferred from name order for exactly this reason), and it
gives no way to express non-CRUD operations, nested resources, or custom
verbs.

**Option 2 — explicit `api { }` block (recommended direction).** A new
grammar block, parallel in spirit to `auto projections` and `index { }`,
binding HTTP method + path + request/response projection + status codes
explicitly:

```mdl
api Customer @ 1 {
  operation "createCustomer" {
    method: POST
    path: "/customers"
    request: CustomerRequest @ 1
    responses {
      201: CustomerReply @ 1
      409: ConflictError @ 1
    }
  }
  operation "getCustomer" {
    method: GET
    path: "/customers/{customerId}"
    responses {
      200: CustomerReply @ 1
      404: NotFoundError @ 1
    }
  }
}
```

This keeps routes as reviewable, versioned, compiler-validated contract the
same way field numbers and service RPCs are today — an operation rename or
removal becomes a diagnosable compatibility event, and path parameters can
be checked against the referenced projection's `@key` field instead of
being free-standing strings. This is genuine new language surface and
belongs in Priority 6 (Lane L): it needs an accepted design and, per
`AGENTS.md`/roadmap policy, concrete consumer demand before implementation
starts — flagging it here rather than folding it into this document's
acceptance.

**Option 3 — external route mapping file** (YAML/JSON alongside `.mdl`,
not in the grammar). Avoids a grammar change entirely but creates exactly
the "second source of truth" problem §3 rejects, and loses compiler
validation of path parameters against `@key` fields. Not recommended.

A standard error-response schema is also needed for Phase B regardless of
which option is chosen (`ConflictError`/`NotFoundError` above need a shape).
RFC 9457 (`application/problem+json`) is the natural choice, consistent with
the project's pattern of adopting an external standard rather than inventing
one (JSON Schema 2020-12, FHIR R4, OpenLineage, ODCS all follow this
pattern already). This should ship as a built-in Modelable-standard
projection shape, analogous to how the change-event envelope is a standard
shape referenced by `event` auto-projections (`docs/language-reference.md`
§3.7, "the standard change event envelope defined in the system spec
section 6.1").

Security scheme declaration (API keys, OAuth2, mTLS) is a natural extension
of the same `api { }` block once it exists, but is out of scope for the
initial Option 2 proposal.

## 8. Phase C — OpenAPI Import Hardening

Independent of A/B, and already named P0 in `ROADMAP.md` Priority 5. Current
state: `cli/src/modelable/llm/importers.py::_import_openapi` is LLM-assisted
and, per the roadmap, "stop treating the first `components.schemas` entry as
the whole API" is an open defect. Concrete work, reusing Phase A's mapping
table in reverse:

1. Move deterministic OpenAPI parsing out of `llm/importers.py` into a
   compiler/application-level format-adapter registry, per Priority 5's
   "Format adapter and regression-test foundation" (already planned
   independent of this design).
2. Accept both YAML and JSON OpenAPI documents.
3. Walk every `components.schemas` entry, not just the first.
4. Map: reusable component schemas → value/entity candidates; request
   bodies/parameters → request projections; responses → reply projections;
   `$ref` → named references; operation/security metadata → whatever
   Modelable concept exists once Phase B lands (or a diagnostic noting it's
   dropped, before Phase B lands).
5. Preserve any `x-modelable*` extension emitted by Phase A through a
   round-trip (import → emit → re-import semantic-equivalence test), per
   the Priority 5 format-adapter checklist.
6. Emit explicit lossy-import diagnostics for OpenAPI constructs with no
   Modelable representation yet (`oneOf`/`anyOf` before D4,
   `pattern`/`minimum`/`maximum` before D2, `nullable` distinctions before
   D1) instead of silently dropping them.

## 9. Testing Strategy

Follows the existing emitter test pattern (`cli/tests/`, mirrored on
`emitters/json_schema.py`/`emitters/protobuf.py` tests) plus the Priority 5
format-adapter checklist:

- Deterministic golden-file tests: same input graph → byte-identical
  `openapi.json` across runs.
- Unit coverage per IR type-mapping row in §6.3, including the
  `type_loss` diagnostic path for unions/constraints once D2/D4 exist.
- Validate every emitted document against the OpenAPI 3.1 JSON Schema
  meta-schema (`Draft202012Validator`-style, already a project dependency
  per `json_schema.py`'s use of the `jsonschema` package) as a CI smoke
  test — parallel to the FHIR emitter's optional smoke against the
  HL7 Java FHIR Validator.
- Phase C: import → emit → re-import semantic-equivalence tests once both
  directions exist, plus malformed/unsupported-feature fixtures that assert
  a clear diagnostic rather than silent loss.
- Add `emitters/openapi.py` (Phase A) and its import counterpart to
  `cli/coverage-baseline.txt` only if/when a future Slice G1-style pass
  decides OpenAPI belongs on the critical-path ratchet; not required for
  initial acceptance.

## 10. Documentation and Rollout

- `docs/compiler-reference.md` §2: flip `OpenAPI | 5 | Deferred` to
  `Implemented local artifact` (Phase A) once shipped, matching the
  Protobuf/gRPC row style.
- `docs/architecture.md` line 1207: remove OpenAPI from the "Deferred" list;
  update the "import-only support exists via LLM-assisted generators" note
  once Phase C lands.
- `docs/language-reference.md` §4.3: `openapi` moves from "declared but no
  implemented emitter behind it" to a real target; if Phase B's `api { }`
  block is accepted, it gets its own numbered subsection there, parallel to
  §3.7 (Auto Projections) and §3.9-equivalent (`index { }`).
- `ROADMAP.md`: resolve the Priority 5 vs. Priority 6/Slice F2 tension noted
  in §2 by updating Slice F2 to point at this document and clarify that only
  Phase D (fidelity) is gated on D1-D4, not Phase A's existence.
- `CHANGELOG.md`: `### Added` entry under `[Unreleased]` per `AGENTS.md`,
  same PR as the Phase A implementation.

## 11. Open Questions

1. Per-domain output files vs. one workspace-wide `openapi.json` — precedent
   exists for both (FHIR/ODCS are per-artifact; some emitters bundle by
   domain). Implementation-plan decision, not blocking this design.
2. Whether `{Entity}Event` schemas belong under `components.schemas` at all
   before Phase B has anywhere to reference them (webhooks section), or
   should wait.
3. Exact Option 2 grammar in §7 (`api { }`) needs its own accepted design
   pass and concrete consumer demand before implementation, per Priority 6
   policy — this document proposes it as the recommended direction, not as
   accepted syntax.
4. Whether Phase A should be gated behind the same "concrete deployment"
   bar Priority 5's closing paragraph sets for the rest of that priority, or
   whether schema-only emission is low-risk enough to ship without one.

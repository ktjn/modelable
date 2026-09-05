# Typed Semantic Facets

## Status

Implemented design for roadmap slice K. The shipped facet model adds extensible,
typed governance facts without adding organization-specific annotations to the
`.mdl` grammar.

## Problem and outcome

Modelable has a deliberately small set of universal governance concepts. Organizations also need facts such as retention class, jurisdiction, data subject, and confidentiality. Those facts must be validated, preserved, inherited, queried, and used by policy without making each new concept a parser or compiler-language change.

The outcome is a normalized facet model shared by semantic analysis, policy evaluation, plans, and query results. A facet is a versioned, namespaced fact attached to an allowed semantic subject. Its propagation behavior is explicit and its source is inspectable. Unknown facets survive round trips but are never interpreted without a matching schema.

## Goals

- Define a canonical facet identity: namespace, name, and schema version.
- Validate facet values using a deterministic JSON-Schema-like subset.
- Define the declaration and path subjects that may carry each facet.
- Make inheritance and projection propagation explicit and deterministic.
- Preserve unknown facets canonically, with an uninterpreted state.
- Let policy, plan, and query consumers inspect the same representation.
- Keep target-specific representation metadata in overlays.
- Demonstrate the model with four governance examples without adding grammar syntax.

## Non-goals

- Adding new `.mdl` annotation or expression syntax for arbitrary facets.
- Replacing the existing built-in identity, ownership, classification, PII, deprecation, or lineage model.
- Making every facet a blocking validation or compatibility failure.
- Defining an organization-wide registry service or network lookup.
- Moving SQL, OpenAPI, protobuf, or other target representation metadata into facets.
- Allowing executable behavior or policy code inside a facet value.

## Canonical model

The compiler represents one facet as:

```text
Facet {
  identity: FacetIdentity
  value: JSON value
  subject: FacetSubject
  propagation: PropagationMode
  source: FacetSource
  interpretation: known | unknown
}

FacetIdentity {
  namespace: non-empty qualified identifier
  name: non-empty qualified identifier
  schema_version: positive integer
}
```

`namespace` identifies the authority that owns the schema; it is not a URL and does not trigger network access. The canonical identity string is `namespace/name@schema_version`. Namespace and name use lowercase ASCII segments separated by `.` or `-`; malformed, empty, or ambiguous identities are rejected. Schema versions are integers and are compared exactly; a newer version is unknown until its schema is explicitly available.

`value` is JSON with object keys sorted canonically. The supported schema vocabulary is deliberately finite: `type`, `const`, `enum`, `properties`, `required`, `items`, `minItems`, `maxItems`, `minimum`, `maximum`, `pattern`, and `additionalProperties`. Schemas must be acyclic, bounded by the existing input/resource limits, and reject unsupported keywords rather than silently ignoring them. Values must match the selected schema exactly; numeric, boolean, string, null, array, and object distinctions are preserved.

`FacetSubject` is one of:

```text
declaration(package, declaration_id)
field(package, declaration_id, field_path)
projection(package, projection_id, version)
projection_field(package, projection_id, version, field_path)
```

The schema declares the allowed subject kinds. A facet cannot be attached to a source subject outside that set. Subject identifiers are canonical semantic identifiers, never source-file positions.

`FacetSource` contains the source subject, source location when available, and an optional causal lineage reference. It is metadata for inspection and deterministic diagnostics; it is not part of facet identity or value equality.

## Propagation semantics

Each known facet schema declares one propagation mode:

- `none`: the facet applies only to its source subject.
- `inherit`: eligible descendants inherit the same value unless they provide an explicit replacement; the result records the source subject.
- `project`: a projection carries the facet only when the source field contributes to the projected field. For joins or expressions with multiple sources, all contributing source facets are retained in deterministic source order. A projection cannot invent a propagated facet for a field with no contributing source.

Propagation is computed from the existing semantic dependency/lineage graph after resolution. It never depends on traversal or declaration order. Explicit facets on a destination subject replace an inherited facet with the same identity; they do not merge values. Different identities coexist. Conflicting explicit facets with the same identity on one subject are a semantic error. A missing schema prevents interpretation and propagation, but does not discard the raw facet.

## Unknown facets

Parsing and serialization retain the complete canonical identity, raw JSON value, subject, propagation declaration, and source metadata for an unknown facet. Consumers may display, compare, and carry it through plans and query results, but policy evaluation must treat it as `unknown` and cannot use it as a satisfied typed predicate. Once a schema is supplied locally, the same stored facet may be validated and interpreted; no network lookup is implicit.

Unknown or invalid facets must not be converted into existing built-in governance fields. Invalid known values produce deterministic semantic diagnostics with the facet identity and subject; unknown schemas produce an informational/uninterpreted result rather than a false success.

## Consumer boundaries

The semantic graph is the source of truth. A shared facet projection produces:

- policy inputs containing typed values, identity, subject, interpretation, and provenance;
- plan representations containing canonical facets on declaration and field nodes;
- query results containing facets in stable identity/subject order.

These are read-only projections of the same normalized model, not separate facet stores. The browser protocol and native path use the same JSON shape and deterministic ordering. Stable protocol additions receive checked-in JSON Schema documents and golden fixtures.

Target overlays remain the only place for target-specific names, wire/storage hints, and representation controls. Facets may be carried as governance context in an artifact, but emitters must not treat them as target configuration unless a future explicit target contract says so.

## Examples

The examples use external schemas and data, not new grammar constructs:

- `org.example/retention-class@1`: string enum `transient`, `standard`, `regulated`, or `indefinite`, attached to a field and projected with `project`.
- `org.example/jurisdiction@1`: an object containing an ISO-like region code and legal basis, attached to a declaration or field with `inherit`.
- `org.example/data-subject@1`: string enum `customer`, `employee`, `patient`, or `device`, attached to a field with `project`.
- `org.example/confidentiality@1`: ordered classification enum `public`, `internal`, `confidential`, or `restricted`, attached to a declaration or field with `inherit`.

These examples exercise scalar, object, enum, subject validation, projection, and policy predicates while remaining ordinary schema data.

## Diagnostics and failure behavior

- Invalid identity, schema, subject, or value: deterministic error tied to the facet and subject.
- Duplicate identity on one subject: deterministic conflict error.
- Missing schema: preserve and report as uninterpreted; do not fail compilation solely for absence of optional schema knowledge.
- Illegal propagation or target-overlay placement: deterministic semantic error.
- Resource-limit violations: use existing input/resource-limit error handling.

No failure path performs network access. Any future registry or schema refresh must be an explicit command with provenance and lock metadata.

## Testing and acceptance

The implementation is complete only when the following are covered by focused tests and deterministic fixtures:

1. Identity and schema validation accept canonical inputs and reject malformed or unsupported inputs.
2. Every allowed subject kind works; disallowed subjects and duplicate identities fail.
3. Scalar, object, array, enum, and numeric constraints validate exactly.
4. `none`, `inherit`, and `project` propagation produce stable results through direct, chained, and multi-source projections.
5. Explicit destination values replace inherited values deterministically.
6. Unknown facets round-trip byte-stably, remain visible, and cannot satisfy typed policy predicates.
7. Known facets are available to policy evaluation, plan output, query output, native execution, and browser execution with equivalent JSON.
8. Target overlays remain separate from facets.
9. The four governance examples work without parser changes.
10. Existing compile, validate, query, browser/native equivalence, typing, coverage, and release gates remain green.

The roadmap acceptance criterion is met when an enterprise can add a new typed governance fact and policies around it by supplying a facet schema and data, without modifying the parser, while lineage and projection behavior remains deterministic and inspectable.

## Rollout and compatibility

Facet input is opt-in and absent facets preserve all existing behavior. The normalized representation is additive. Existing consumers that do not understand facets continue to receive valid documents with facets preserved or ignored according to their protocol version. Protocol schema versions advance only when required; unknown facet identities are forward-compatible because their raw values are retained.

# Compiler correction and capability plan

## Status and baseline

This plan was originally validated against `ktjn/modelable` `main` at commit
`38fa89dcc22c0ed5f58458f36aa31f8d316290be` and folded into
[ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) as Priority 3 and part of Priority 6 on
2026-08-03, at commit `540b9f6526db82f92ab4386a2ec17ea501161d70`. The one
commit between those two points (`fix(playground): bump pinned searchable-*
wheels for the browser`, #277) does not touch the compiler paths this plan
covers, so the findings below still hold.

It is a **compiler-correctness and contract-consistency track**. It does not
replace the product roadmap. See [ROADMAP.md](https://github.com/ktjn/modelable/blob/main/ROADMAP.md) for priority
ordering; this document holds the full slice-level detail that ROADMAP.md
links to.

The product roadmap continues in parallel as ROADMAP.md Priorities 1, 2, 4,
and 5:

1. **Playground priority:** extensibility, including plugin contracts,
   additional visualization modes, and optional GitHub integration.
2. **Scalable/Rust/Protobuf priority:** prove Scalable registration end to end
   using generated identity, schema, service, and index metadata.
3. **Authoring/adoption priority:** extend nominal semantic-type support beyond
   Rust according to concrete consumer demand.

The correction track may interrupt those tracks only when a verified
correctness issue can produce an incorrect compatibility decision, incomplete
lineage, invalid generated contract, or silent loss of user input.

## Verified baseline corrections

The following points are based on the current compiler rather than only on
architecture documentation.

### Composite keys are claimed but not implemented consistently

`docs/architecture.md` describes composite keys as supported and includes an
entity with two `@key` fields.

However:

- `cli/src/modelable/validation/semantic.py` requires exactly one `@key` field
  for every entity and aggregate (verified at `semantic.py:177`).
- `docs/language-reference.md` states that composite keys are not currently
  representable.
- The existing multi-domain join fixture describes a composite relationship,
  but its entities still each have one declared key and its join does not
  establish composite entity identity.

Composite keys therefore remain a real implementation/specification
contradiction. The plan retains the topic, but first resolves whether the
architecture claim should be implemented or corrected.

### Protobuf and gRPC compatibility already have target-specific guards

`validate-compat --target protobuf|grpc` already checks several wire-contract
changes (verified in `cli/src/modelable/commands/validate_compat.py` and
`cli/src/modelable/compat/checker.py`). This plan must generalize that work
rather than introduce a parallel compatibility framework.

### Current active roadmap tracks remain authoritative

This plan runs beside, not above, ROADMAP.md Priorities 1, 2, 4, and 5.

### Immediate optionality correction is a stopgap

The current language has one `optional` flag and uses `?`. `nullability_changed`
and related concepts already exist in `cli/src/modelable/compat/diff.py`, but
the compatibility summary does not consistently classify `optional ->
required` as breaking (verified). The immediate compatibility bug must still
be fixed now. A later presence/nullability design must deliberately replace or
extend those temporary rules without reinterpreting historical published text
accidentally.

---

# Delivery model

## Parallel lanes

### Lane P1 — active product work

Continue the accepted Playground extensibility slice. ROADMAP.md Priority 1.

### Lane P2 — active integration work

Continue the Scalable registration end-to-end slice. ROADMAP.md Priority 2.

### Lane C — compiler correction work

Start with compatibility, lineage, and expression-validation correctness.
ROADMAP.md Priority 3 (this document's Tracks A, B, C, G).

### Lane L — future language evolution

Do not start syntax-changing work until the historical interpretation policy
is accepted — with the exception of additive-only grammar (see Track H,
which does not reinterpret any existing syntax and therefore does not need
the D0 gate). ROADMAP.md Priority 6 (this document's Tracks D, E, F2-F4, H).

## Interleaving rules

1. A confirmed false compatibility result is a release blocker.
2. Silent loss or ignored parsed content is a release blocker for the affected
   construct.
3. Incomplete diagnostics that do not change compiler output may proceed beside
   active roadmap work.
4. New broad language features do not preempt the two active product tracks
   without a concrete consumer and accepted design.
5. Every slice must be rechecked against `main` immediately before design
   acceptance.

---

# Track A — correctness fixes

## Slice A1 — correct optionality compatibility under the current model

### Purpose

Fix the current compatibility bug without waiting for a future
presence/nullability redesign.

### Current problem

The model diff can emit `nullability_changed`, but the compatibility summary
does not consistently classify `optional -> required` as breaking. Semantic
validation and compatibility reporting can therefore disagree.

### Scope

- Classify `required -> optional` as compatible.
- Classify `optional -> required` as breaking.
- Use `optionality_changed` terminology internally and in new machine-readable
  output where practical.
- Preserve legacy textual wording only when changing it would break a stable
  interface.
- Make semantic version validation and compatibility reporting call the same
  rule.

### Explicit lifetime

This is a **stopgap for the current single-flag model**.

A later presence/nullability slice must:

- preserve these results for equivalent transitions;
- migrate tests to the new two-dimensional model;
- remove temporary terminology only through a documented compatibility change.

### Tests

- required to optional;
- optional to required;
- optional field addition;
- required field addition;
- rename plus optionality change;
- additive declaration validation;
- compatibility report classification;
- target-specific requiredness checks remain consistent.

### Acceptance criteria

- No optional-to-required change is reported as compatible.
- Semantic validation and compatibility reports agree.
- Existing optional-field additions remain compatible.

---

## Slice A2 — create one property-dependency graph

### Purpose

Replace duplicated and incomplete source-property analysis.

### Scope

Introduce a compiler-owned dependency graph that records property use in:

- direct mappings;
- computed expressions;
- join predicates;
- filters;
- grouping expressions;
- projection-as-source chains;
- exact, pinned, range, and minimum-version references.

Suggested record:

```python
@dataclass(frozen=True)
class PropertyDependency:
    consumer_ref: str
    target_property: str | None
    usage_kind: Literal[
        "direct",
        "computed",
        "join",
        "filter",
        "group",
    ]
    source_ref: str
    source_property: str
```

Use it from:

- compatibility impact analysis;
- governance validation;
- lineage reports;
- graph export;
- LSP and Playground analysis views;
- dependent lookup.

### Constraints

- Version resolution must use the existing canonical resolver.
- Source ranges must resolve using the rules already defined for projection
  source references.
- No subsystem may independently parse CEL merely to rediscover lineage.

### Tests

- direct mapping;
- computed expression;
- join predicate;
- `where`;
- `group by`;
- exact source;
- pinned source;
- range source;
- minimum-version source;
- chained projection source;
- multi-source property usage.

### Acceptance criteria

- All property-use paths are visible through one API.
- Compatibility and governance use the same source-property graph.
- Range and pinned dependencies are not missed.

---

## Slice A3 — validate all expression positions

### Purpose

Ensure parsed expressions cannot bypass semantic validation.

### Scope

Run the same CEL pipeline for:

- computed fields;
- join predicates;
- `where` clauses;
- `group by` expressions;
- supported expression-bearing annotations.

Validate result shape:

- `where` is boolean;
- join predicates are boolean;
- grouping expressions are valid scalar source expressions;
- aliases and properties exist;
- computed result types are resolved where supported.

### Tests

- unknown alias in `where`;
- unknown field in `where`;
- non-boolean filter;
- invalid group expression;
- unknown join field;
- invalid computed expression;
- dependency extraction from every expression position.

### Acceptance criteria

- Every expression-bearing construct is parsed, typed, and traced.
- Invalid filters and grouping expressions fail compilation.
- The dependency graph includes expression-only dependencies.

---

## Slice A4 — fix semantic-type resolution ambiguity

### Purpose

Make semantic-type identity deterministic across domains.

### Current problem

Semantic declarations are unique only inside a domain, while bare named-type
resolution is workspace-wide. A flat name dictionary can silently select one
of two declarations with the same name.

### Proposed resolution rules

1. A bare name resolves in the current domain first.
2. A qualified name such as `orders.Id` resolves across domains.
3. A bare name may fall back to a workspace-wide match only when exactly one
   declaration exists.
4. Ambiguity is a compile error.

### Scope

- Add qualified semantic-type references.
- Preserve declaring domain in semantic identity.
- Include qualified identity in canonical signatures and manifests.
- Update emitters, hover, completion, definition, rename, and import handling.
- Detect cross-domain semantic chains and cycles.

### Tests

- same-domain shorthand;
- qualified cross-domain use;
- duplicate names in separate domains;
- ambiguous bare reference;
- cross-domain chain;
- cycle across domains;
- stable signatures.

### Acceptance criteria

- Resolution never depends on file or iteration order.
- Semantic identity is domain-aware.
- Existing unambiguous references continue to work.

---

# Track B — capability and documentation consistency

## Slice B1 — add a canonical capability manifest

### Purpose

Use compiler-owned data to answer what Modelable supports.

### Manifest contents

- output targets and status;
- SQL dialects;
- model kinds;
- annotations;
- wire hints;
- projection features;
- import formats;
- integrations;
- experimental and deferred grammar constructs;
- CLI, LSP, browser, and Playground capabilities.

Suggested command:

```bash
modelable capabilities
modelable capabilities --format json
```

### Consumers

- CLI target listing;
- Playground menus;
- README capability table;
- language and compiler references;
- documentation consistency tests;
- release checks.

### Acceptance criteria

- Stable documentation cannot list an unsupported target unnoticed.
- Deferred features are explicitly labelled.
- CLI and Playground capability lists derive from compiler-owned data.

---

## Slice B2 — reconcile current documentation claims

### Purpose

Correct verified contradictions without assuming all documents are equally
wrong.

### Verified topics

- Architecture claims composite keys; validator and language reference do not.
- Architecture describes model lifecycle statuses and constraints that are not
  represented by the current stable grammar/IR.
- Language reference accepts or lists targets that the target registry marks
  deferred or does not expose.
- Federation and runtime-adjacent constructs are described more strongly than
  their current implementation status.
- Classification vocabulary must include the same values everywhere.
- README, ROADMAP, browser documentation, and implementation must agree on
  shipped browser language services.

### Composite-key subtask

Do not assume the architecture claim is correct merely because it says
"resolved."

Perform a focused decision:

1. Add a conformance test with two `@key` fields.
2. Record current failure.
3. Choose:
   - implement composite entity identity; or
   - mark it deferred and correct architecture.
4. Update language reference and architecture together.

### Acceptance criteria

- Each capability has one status: implemented, experimental, deferred,
  candidate, or removed.
- Composite-key documentation matches an executable conformance test.
- Unsupported examples are clearly labelled.

---

## Slice B3 — eliminate silently ignored syntax

### Purpose

Ensure successful parsing implies meaningful handling.

### Review

- registry and peers;
- consumers;
- subscriptions;
- materialisation;
- bindings with opaque nested blocks;
- deferred generation targets;
- generic ignored blocks.

### Allowed outcomes

For each construct:

1. fully parse and validate it;
2. represent it as explicit experimental IR and diagnose it;
3. reject it as deferred;
4. remove it from stable grammar.

### Acceptance criteria

- Stable syntax is never discarded as ignored text.
- Unsupported content produces an explicit diagnostic.
- Canonical rendering cannot erase unhandled user declarations.

### Outcome chosen (2026-08-05)

Registry, peers, consumers, subscriptions (both forms), materialisation, and
opaque `binding {}` content are outcome 3, "reject as deferred," implemented
as a non-blocking warning-severity `DEFERRED` diagnostic
(`cli/src/modelable/validation/deferred_syntax.py`) rather than outcome 2
("explicit experimental IR"). Full IR representation is federation/runtime
design work — a registry/peer model, a consumer-tracking model, a
subscription/materialisation runtime model — that does not exist and is
disproportionate to a syntax-correctness slice; it needs its own
`superpowers:brainstorming` pass per construct once there is a product
decision to build it (see ROADMAP.md "Outside the near-term compiler
roadmap"). The diagnostic is non-blocking specifically because these
constructs are used in curated sample scenarios (03, 06, 07, 08) that
`test_samples.py` asserts validate cleanly; a blocking diagnostic would
require rewriting those scenarios in the same slice, which is out of
proportion to a diagnostics-only fix.

`generate_targets` (bucket b — round-tripped by `compiler/render.py` but
never emitted) and the recognized `binding {}` attributes (`adapter`,
`model`, `table` — bucket a, genuinely consumed by `emitters/sql.py` and
`emitters/rust.py`) were confirmed via Slice B2 research and are unaffected
by this change.

New `deferred_features` entries in `cli/src/modelable/capabilities.py`
(`workspace-registry`, `workspace-peers`, `consumer-declarations`,
`subscriptions`, `materialisation`, `binding-opaque-content`) give
`modelable capabilities` the authoritative status each diagnostic points to.

---

# Track C — compatibility architecture

## Slice C1 — projection-to-projection compatibility

### Purpose

Treat versioned projections as first-class consumer contracts.

### Compare

- output shape;
- property names and types;
- optionality;
- lineage source changes;
- expression changes;
- filters;
- joins and cardinality;
- grouping and aggregation;
- source-version changes;
- access and governance;
- event operation coverage;
- target wire effects.

### Dependency

Requires A2 and A3.

### Output dimensions

- shape;
- lineage;
- governance;
- wire;
- storage;
- materialisation.

### Acceptance criteria

- Projection versions can be compared directly.
- Same-shape lineage changes remain visible.
- Findings identify affected dimensions and source properties.

### Outcome (2026-08-05)

Implemented as designed in
[the C1 design spec](superpowers/specs/2026-08-05-projection-compatibility-design.md):
`compare_projection_versions()`/`check_projection_version_compatibility()`
in `compat/diff.py`/`compat/checker.py`, wired into the existing
`modelable diff` command (`ResolvedModelRef.version` already resolved both
models and projections uniformly — `run_diff` just never branched on it).
Per-dimension tagging with a single overall rollup status. Source-version
comparison delegates entirely to `check_model_version_compatibility()` —
no independent "is this breaking" logic for model version bumps.
`materialisation` and `event operation coverage` are not populated (both
genuine IR gaps, not oversights — see the design doc and the
`projection-event-operation-coverage-compatibility` capability manifest
entry).

---

## Slice C2 — extend existing version resolution to `ref<>` types

### Purpose

Apply the already-defined projection-source version rules to model-reference
type positions.

### Existing foundation

Projection sources already support:

- exact versions;
- ranges;
- minimum versions;
- content pins;
- highest-satisfying resolution;
- blocking across breaking versions.

Do not redesign those rules.

### Net-new scope

Support version syntax in type references:

```mdl
ref<customer.Customer @ 2>
ref<customer.Customer @ >=2 <3>
ref<customer.Customer @ 2#hash>
```

Define temporary behaviour for existing unversioned refs.

Recommended compatibility path:

- Existing unversioned `ref<Domain.Model>` continues to parse.
- It resolves under an explicit legacy rule.
- Compilation records the concrete resolved identity.
- A diagnostic recommends adding a version constraint where durable identity
  matters.

### Acceptance criteria

- `ref<>` resolution reuses the canonical source resolver.
- Resolved reference identity participates in signatures and compatibility.
- Existing files have a documented interpretation.

### Outcome (2026-08-05)

Implemented as designed in
[the C2 design spec](superpowers/specs/2026-08-05-ref-version-resolution-design.md):
grammar/IR support for `ref<Domain.Model @ version_spec>`, one canonical
`resolve_ref_type()` resolver, new SEM validation for unresolvable refs and
a non-blocking `REF` advisory for unversioned ones, compat/signature rules
that separate a ref's target (breaking if changed) from its version
(never breaking alone), TypeScript codegen using the ref's own version
instead of always-latest, and consolidation of the LSP's two independently
duplicated "unversioned ref → latest" implementations onto one shared
helper.

---

## Slice C3 — generalize existing target compatibility

### Purpose

Build a target-agnostic compatibility report around the already-shipped
Protobuf and gRPC guards.

### Existing implementation to reuse

Protobuf/gRPC validation already covers several wire changes, including:

- field-number reuse;
- deleted-field reservations;
- target type changes;
- requiredness;
- inline enum value reuse;
- gRPC read-index changes.

### Scope

- Define a common target-compatibility result IR.
- Adapt current Protobuf/gRPC validators to emit it.
- Preserve existing CLI behaviour during migration.
- Extend the model to:
  - JSON representation;
  - SQL/storage migration;
  - projection rebuild;
  - governance review.
- Avoid duplicating Protobuf/gRPC rule logic.

Suggested axes:

```text
source_compatibility
wire_compatibility
storage_migration
projection_rebuild
governance_review
```

Suggested severities:

```text
compatible
review_required
migration_required
breaking
```

### Acceptance criteria

- Existing Protobuf/gRPC checks use the common IR.
- No second parallel compatibility engine is introduced.
- SQL/index changes can report migration requirements.
- Expression-only projection changes can report rebuild requirements.

### Outcome (2026-08-06)

Implemented directly on top of the shipped guards rather than a rewrite:
`compat/targets.py` now defines one shared IR — `AXES`
(`source_compatibility`, `wire_compatibility`, `storage_migration`,
`projection_rebuild`, `governance_review`) and `SEVERITIES` (`compatible`,
`review_required`, `migration_required`, `breaking`) — and every comparator
in the module, old and new, returns `TargetCompatibilityReport`/
`TargetCompatibilityFinding` through it. `compare_protobuf_manifests()` and
`compare_grpc_artifacts()` are unchanged in behavior (same status text, same
`validate-compat` output, same exit codes — the existing CLI tests pass
unmodified) but now also tag every finding with `axis="wire_compatibility"`
and a mapped `severity`, via one `_STATUS_TO_SEVERITY` table rather than a
second classification path.

Four new comparators extend the IR to the axes the slice called for, each
reusing an existing diff primitive instead of re-deriving one:

- `compare_source_representation()` — wraps `compat/diff.py`'s
  `FieldChange` list (via the new shared `is_field_change_breaking()`
  classifier, extracted from `checker.py::_has_breaking_change` so there is
  one breaking-change predicate, not two) as `source_compatibility`. This is
  also the JSON-representation axis: JSON Schema emission adds no
  wire-format constraints beyond the shared model contract, so a
  `target="json-schema"` call is the same function, not a parallel one.
- `compare_storage_migration()` — wraps `compare_index_decls()`'s index
  changes as `storage_migration`/`migration_required`. Scoped to declared
  index changes only, matching the acceptance criterion ("SQL/index changes
  can report migration requirements"); column-level DDL migration necessity
  (e.g. a type change requiring a backfill) is not covered and would need
  its own design.
- `compare_projection_rebuild()` — wraps `compare_projection_versions()`'s
  `storage` and `lineage` dimensions as `projection_rebuild`. A
  `lineage`-dimension change (remapped source, changed computed expression)
  is compatible today but always needs a materialized/stored rebuild — this
  is the concrete "expression-only projection changes can report rebuild
  requirements" case.
- `compare_governance_review()` — wraps the `governance` dimension as
  `governance_review`, mapping a non-breaking governance change (grant
  added, classification loosened) to `review_required` rather than folding
  it into a flat `compatible`.

`checker.py`'s `_format_finding`/`_bool_word` moved to `diff.py` as public
`describe_field_change`/`describe_bool_word`, reused by both the model-diff
finding text and the new source-compatibility axis.

Deliberately out of scope, left as library-level API rather than wired into
`validate-compat`/`modelable diff` CLI output: the acceptance criteria are
about the IR ("the model can report"), and the plan explicitly requires
preserving existing CLI behavior during this migration. New `--target`
CLI wiring for `json-schema`/`sql-postgres` is a separate, larger increment
(those targets diff whole workspaces via emitted artifacts, a different
granularity than `checker.py`'s single-model-version-pair functions this
slice reuses) and is left for whoever picks up C4's policy layer or a
follow-on CLI slice.

---

## Slice C4 — configurable compatibility and lint policy

### Purpose

Allow teams to set enforcement policy without changing semantic truth.

Example:

```yaml
compatibility:
  source: strict
  protobuf: wire
  grpc: wire
  sql: migration-required
  json: backward

lint:
  require_descriptions: warning
  require_classification: error
```

### Acceptance criteria

- Structural errors remain unsuppressible.
- Policy controls severity, not compiler facts.
- Target axes can be enforced independently.

### Outcome (2026-08-06)

Implemented the `compatibility:` half; the `lint:` half in the example above
(`require_descriptions`/`require_classification`) has no existing linter to
attach severity to and remains undesigned — a policy file that includes a
`lint:` section is rejected with a clear error rather than silently
discarded, per the same "no silent loss of parsed content" standard Slice B3
set.

`compat/policy.py` adds `CompatibilityPolicy`: a per-`TargetCompatibilityReport.target`
mapping to one of Slice C3's four `SEVERITIES`, the minimum finding severity
that fails that target. `load_policy()` parses it from a YAML file (the
`.github/scripts` baseline-file / `specs/tracking.py` precedent: plain
`ValueError` on a malformed file, caught and re-raised as
`click.ClickException` at the CLI boundary). `validate-compat` gained an
optional `--policy <path>` option; omitting it preserves the exact
pre-Slice-C4 behavior (only a fully `compatible` report passes) through the
original, untouched `PASSING_STATUSES` code path — the policy path is
additive, not a replacement.

The three acceptance criteria are satisfied structurally, not just by
convention: `SEVERITIES` is a fixed, ordered tuple with `breaking` as its
maximum, and a policy threshold must be a member of that tuple — so a
`breaking` finding's rank is always >= any valid threshold's rank, and no
policy value exists that could suppress one (**structural errors remain
unsuppressible**). `CompatibilityPolicy.enforce()` reads
`TargetCompatibilityFinding.severity`, computed once by `compat/targets.py`
and never written by the policy layer (**policy controls severity
enforcement, not the compiler-determined facts**). Thresholds are keyed by
target and looked up independently per report (**target axes enforced
independently** — e.g. a stricter gate on `protobuf` than on
`governance-review` in the same policy file).

Deliberately out of scope: `modelable diff`'s `CompatibilityReport`/
`ProjectionCompatibilityReport` (`compat/checker.py`) carry plain
`findings: list[str]`, not the axis/severity IR this policy is defined over
— wiring `--policy` into `diff` would mean threading the Slice C3 IR through
`checker.py` first, a separate, larger change the plan doesn't ask for here.

---

# Track D — language evolution safeguards and features

## Slice D0 — define historical language interpretation

### Purpose

Protect immutable published `.mdl` text before changing syntax meaning.

### Required decision

Choose one policy before D1 or lifecycle syntax lands:

1. **Additive-syntax policy:** old syntax never changes meaning; new semantics
   require new syntax.
2. **Language-version policy:** workspace or source files declare a language
   version, and historical text is interpreted under that version.
3. **Compiler-version snapshot policy:** published contracts record the
   compiler/language version required to interpret them.

The preferred default is additive syntax unless a concrete feature cannot be
expressed safely.

### Required outputs

- interpretation rules for historical published files;
- canonical signature behaviour;
- registry rebuild behaviour;
- formatter behaviour;
- upgrade and migration diagnostics;
- browser/native parity requirements.

### Acceptance criteria

- Upgrading Modelable cannot silently change the meaning of published text.
- Historical signatures remain reproducible.
- New syntax has an explicit compatibility story.

---

## Slice D1 — separate presence and nullability

### Purpose

Represent absence and explicit null independently.

### Dependency

Requires D0.

### Migration requirement

Do **not** silently change the meaning of existing `field?`.

The design must define one of:

- preserve `?` as legacy optionality and add separate nullable syntax; or
- interpret `?` under an explicit language version.

### Desired states

- required, non-null;
- optional, non-null;
- required, nullable;
- optional, nullable.

### Acceptance criteria

- Existing published text keeps a deterministic meaning.
- Compatibility reports distinguish presence from nullability.
- Every emitter declares exact or lossy representation.

---

## Slice D2 — first-class constraints

### Purpose

Track valid property values in addition to structural shape.

### Initial set

- numeric minimum and maximum;
- length limits;
- pattern;
- format;
- item-count limits;
- uniqueness.

### Modelable-specific requirement

Each constraint must define:

- valid source types;
- propagation through direct projections;
- narrowing and widening;
- compatibility impact;
- target support and loss diagnostics.

### Acceptance criteria

- Constraint lineage is explicit.
- Constraint widening cannot occur silently.
- JSON Schema and supported language outputs preserve enforceable constraints.

---

## Slice D3 — named enums

### Purpose

Create reusable, version-aware vocabularies.

### Scope

- domain-qualified identity;
- value evolution;
- wire values;
- Protobuf numbering and reservations;
- compatibility across targets.

### Acceptance criteria

- Repeated inline enum vocabularies can become named contracts.
- Value evolution has source and wire compatibility rules.

---

## Slice D4 — discriminated unions

### Purpose

Represent variant-based contracts, especially event families.

### Dependency

Requires stable enum, nullability, and target-compatibility semantics.

### Acceptance criteria

- Variants have stable identity and discriminator values.
- Adding/removing variants is compatibility-classified.
- Every emitter preserves semantics or emits an explicit loss diagnostic.

---

## Slice D5 — resolve composite-key support

### Purpose

Close the verified architecture/compiler contradiction.

### Phase 1: decision and conformance

- Add an executable fixture containing two `@key` fields.
- Verify current validation failure.
- Decide whether composite identity is in stable scope.
- Correct architecture immediately if the feature is deferred.

### Phase 2: implementation, if accepted

- Allow one or more key fields for entities and aggregates.
- Require deterministic ordering.
- Reuse `index { primary ... }` where present.
- Define fallback ordering when no index declaration exists.
- Update:
  - canonical signatures;
  - compatibility;
  - SQL;
  - Protobuf/gRPC manifests;
  - generated languages;
  - event envelopes;
  - `ref<>` identity;
  - joins and relation validation.

### Important distinction

Multi-column join predicates and composite entity identity are separate
features. Supporting a join involving several properties does not prove that
multiple `@key` fields are supported.

### Acceptance criteria

- Documentation status is backed by a conformance test.
- If implemented, key order and identity are deterministic across targets.
- Existing single-key signatures remain stable where possible.

---

## Slice D6 — model lifecycle status

### Purpose

Either implement or remove architecture claims for draft, published,
deprecated, and retired versions.

### Dependency

Requires D0.

### Backward interpretation

Existing versioned declarations must have an explicit default status, most
likely `published`.

### Semantics to define

- draft mutability;
- published immutability;
- deprecated resolution warnings;
- retired range resolution;
- legal transitions;
- interaction with required change kind;
- signatures and registry records.

### Acceptance criteria

- Existing published text is not reinterpreted unpredictably.
- Status affects resolution and diagnostics consistently.
- Architecture claims match compiler behaviour.

---

# Track E — extensibility and data-contract breadth

## Slice E1 — typed namespaced annotations

### Purpose

Support organizational metadata without adding every concept to the core
language.

### Grammar prerequisite

The current grammar has a closed set of single-token built-in annotations.
Names such as:

```mdl
@acme.retention("7y")
```

require a grammar and IR extension before plugin safety behaviour can exist.

### First sub-slice

- add namespaced annotation identifiers;
- define typed argument syntax;
- preserve unknown annotation text losslessly;
- reject unsupported annotations under strict policy;
- provide deterministic canonical rendering.

### Plugin contract

Each extension declares:

- namespace and version;
- annotation schema;
- valid targets;
- compatibility significance;
- propagation rules;
- validation hooks;
- emitter behaviour.

### Acceptance criteria

- Namespaced annotations parse and render deterministically.
- Unknown annotations are never silently discarded.
- Plugin activation is explicit and reproducible.

---

## Slice E2 — data-quality contract metadata

### Purpose

Represent quality expectations while leaving execution to external tools.

### Initial rules

- non-null;
- uniqueness;
- accepted values;
- ranges;
- row-count thresholds;
- referential integrity;
- external test reference.

### Outputs

- ODCS;
- dbt tests;
- OpenMetadata contract metadata;
- machine-readable Modelable graph.

### Acceptance criteria

- Rules reference valid properties.
- Quality changes appear in compatibility output.
- Modelable validates definitions but does not become a scheduler.

---

## Slice E3 — freshness, SLA, and retention metadata

### Purpose

Cover broader data-contract expectations already represented by supported
external formats.

### Semantics

Define model/projection ownership, inheritance, compatibility significance,
duration syntax, timezone handling, and target mappings.

### Acceptance criteria

- SLA metadata is source-controlled and validated.
- Supported contract/catalog emitters preserve it.
- Changes are visible as review or compatibility findings.

---

# Track F — target and roadmap-aligned work

## Slice F1 — nominal semantic types beyond Rust

### Status

This directly aligns with ROADMAP.md Priority 4 item 4 and remains valid.

### Priority

Follow concrete consumer demand, with the roadmap ordering as the starting
point:

1. TypeScript;
2. Go;
3. Java;
4. C#;
5. Python;
6. JSON Schema;
7. SQL.

Each target must state whether it preserves or intentionally erases nominal
identity.

---

## Slice F2 — OpenAPI after constraints and unions

Dependencies:

- D1;
- D2;
- D3;
- D4;
- C1;
- C3.

Do not treat grammar acceptance of `openapi` as implemented emitter support.

---

## Slice F3 — AsyncAPI after event-union semantics

Dependencies:

- named enums;
- unions;
- reference-version semantics;
- event-envelope contract;
- target-aware compatibility.

---

## Slice F4 — Avro after target compatibility is mature

Dependencies:

- defaults;
- nullability;
- named enums;
- unions;
- target-specific reader/writer compatibility.

---

# Track G — engineering safeguards

## Slice G1 — critical compatibility coverage

Protect:

- model compatibility;
- projection compatibility;
- dependency resolution;
- expression validation;
- lineage;
- governance;
- signatures;
- target compatibility.

Use per-module or per-critical-path ratchets rather than only a repository-wide
percentage. See also
[engineering-roadmap.md](engineering-roadmap.md) item 2 (CLI coverage
visibility), which this slice extends with critical-path ratchets.

## Slice G2 — strict typing baseline reduction

Priority:

1. compatibility and dependency graph;
2. resolver and signatures;
3. semantic validation;
4. parser/IR;
5. emitters;
6. importers;
7. conversational surfaces.

This is the same baseline ratchet tracked in
[engineering-roadmap.md](engineering-roadmap.md) item 1, ordered here by
critical-path priority.

## Slice G3 — conformance fixtures

Share fixtures across:

- native compiler;
- browser compiler;
- LSP;
- Playground;
- compatibility;
- signatures;
- manifests.

Include explicit fixtures for every capability disputed by documentation,
especially composite keys and deferred constructs.

### First tranche shipped (2026-08-05)

Of the 7 named areas, only native compiler + browser compiler + Playground
had a working shared-fixture pipeline (`cli/tests/conformance/browser/` →
`vendor-python-assets.mjs` → `conformance.spec.ts`). This tranche extended
that pipeline with the two cases the plan calls out by name: `composite-key`
(SEM error) and `deferred-constructs` (the Slice B3 `DEFERRED` warning),
verified against the real Pyodide browser compiler, not just the native
snapshot generator. Along the way, found and fixed a real gap this fixture
work exposed: `language/workspace.py`'s `synchronize()` — which backs the
browser's diagnostics surface — only read `workspace.errors`, so B3's
warnings were invisible in the browser/Playground despite working in the
CLI. LSP fixture sharing (30 unshared test files, no generator today),
compatibility fixtures, signature fixtures, and capability-manifest-to-test
linkage remain for a later tranche — each is its own scoping exercise, not
a natural extension of the browser pipeline this tranche used.

---

# Track H — authoring ergonomics

## Slice H1 — projection Pick/Omit clauses

### Purpose

Reduce hand-written field-mapping boilerplate for projections that are
mostly-verbatim subsets of their source, without weakening the explicit
per-field lineage guarantee (`docs/language-reference.md:180`).

### Status

Full design accepted:
[Projection Pick/Omit Clauses — Design](superpowers/specs/2026-08-03-projection-pick-omit-design.md).

### Scope (summary — see design for full detail)

- New optional `pick(...)` / `omit(...)` clause on `projection` declarations,
  accepting unqualified field names, qualified `alias.field` names (for
  `join` sources), and annotation filters (`@pii`,
  `@classification("secret")`) reusing `auto projections ... exclude`'s
  existing grammar and matcher.
- Expands to ordinary `<-` direct-mapping IR nodes before semantic
  validation — identical downstream shape to a hand-written projection, so
  compatibility (C1), the shared dependency graph (A2), lineage, governance,
  canonical signatures, and the formatter need no special-casing.
- Deferred to a later slice: `Partial`/`Required`-style bulk optionality
  flips, inline rename while picking, and composing one projection from
  another.

### Why this is not gated behind D0

Unlike D1–D6, this is purely additive grammar: it introduces a new optional
clause and does not reinterpret any existing syntax or change the meaning of
already-published `.mdl` text. It can proceed independently of the historical
interpretation policy.

### Dependency

None strictly required. Landing after A2 is preferred so the "identical to
hand-written" compatibility/lineage tests have the shared graph API to test
against, but this slice does not block on A2.

### Acceptance criteria

See the design doc's acceptance criteria section.

---

# Roadmap interleaving

## Work that should start immediately

### Correction lane

1. A1 — optionality compatibility stopgap.
2. A2 — shared property-dependency graph.
3. A3 — complete expression validation.
4. A4 — semantic-type namespace ambiguity.
5. G1 — critical-path regression tests.

### Product lane

Continue Playground extensibility.

### Integration lane

Continue Scalable registration proof.

The product and integration lanes do not need to wait for A1–A4 unless they
touch affected compatibility or lineage paths.

## Next correction tranche

1. B1 — capability manifest.
2. B2 — documentation reconciliation.
3. B3 — deferred syntax handling.
4. G3 — capability conformance fixtures.

## Compatibility tranche

1. C1 — projection compatibility.
2. C2 — versioned `ref<>`.
3. C3 — generalized target compatibility.
4. C4 — policy profiles.

## Language tranche

1. D0 — historical interpretation policy.
2. D1 — presence/nullability.
3. D2 — constraints.
4. D3 — named enums.
5. D4 — unions.
6. D5 — composite-key decision/implementation.
7. D6 — lifecycle status.

These require accepted designs and concrete consumer demand; they do not
automatically outrank current roadmap priorities.

## Ergonomics tranche

1. H1 — projection Pick/Omit clauses. Unlike the language tranche above, this
   does not need D0 first and can be picked up whenever it is prioritized
   relative to Priorities 1, 2, 4, and 5.

---

# First pull-request sequence

## PR 1 — optionality compatibility correction

- Fix current false-compatible result.
- Add regression tests.
- Mark implementation as the current-model stopgap.

## PR 2 — compiler-owned dependency graph

- Extract direct and CEL-derived property dependencies.
- Support all source version forms.
- Move compatibility and governance onto the shared graph.

## PR 3 — complete expression validation

- Validate filters and grouping.
- Require boolean predicates.
- Feed all expression references into dependency lineage.

## PR 4 — semantic-type namespace resolution

- Add qualified names.
- Reject ambiguity.
- Update signatures, emitters, and editor services.

## PR 5 — capability manifest

- Expose machine-readable capabilities.
- Connect CLI and Playground consumers.
- Add documentation consistency tests.

## PR 6 — specification reconciliation

- Correct composite-key status based on conformance tests.
- Correct target, federation, lifecycle, constraint, classification, and browser
  capability claims.
- Make deferred constructs explicit.

---

# Definition of done

The correction programme (Tracks A–G) is complete when:

- compatibility reports cannot contradict semantic validation;
- every property dependency is captured, including filters and joins;
- all expressions are type-checked and traced;
- semantic types resolve deterministically;
- current capabilities and documentation agree;
- deferred syntax is never silently ignored;
- projection compatibility is first-class;
- `ref<>` uses the existing version-resolution semantics;
- target compatibility generalizes rather than duplicates Protobuf/gRPC work;
- historical published `.mdl` text has a defined interpretation policy;
- presence and nullability can evolve without silently changing old text;
- composite-key status is proven by executable conformance tests;
- lifecycle claims are either implemented or removed;
- namespaced extension syntax is implemented before annotation plugins;
- active Playground and Scalable roadmap tracks remain visible and continue in
  parallel;
- every slice is re-diffed against `main` before implementation.

Track H (authoring ergonomics) is separately done when H1's own acceptance
criteria (in its design doc) are met — it is not gated by the above.

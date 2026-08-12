# `ref<>` Version Resolution — Design

Slice C2 from [docs/correction-and-capability-plan.md](../correction-and-capability-plan.md#slice-c2--extend-existing-version-resolution-to-ref-types).
Part of the Compatibility tranche (C1 ✅ → C2 → C3 → C4).

## Purpose

`ref<Domain.Model>` — a field's type when it references another model —
carries no version information today. Confirmed by reading the grammar
(`ref_type: "ref" "<" dotted_ref ">"`, `modelable.lark:121`) and the IR
(`RefType(BaseModel): kind: Literal["ref"]; target: str`,
`parser/ir.py:201-203`): `.target` is a bare dotted name, nothing else.

This slice extends the existing projection-source version syntax
(`from Model @ 2 as x`, `from Model @ >=2 <3 as x`) to type-reference
position: `ref<Domain.Model @ 2>`, `ref<Domain.Model @ >=2 <3>`,
`ref<Domain.Model @ 2#hash>`.

## Current state (confirmed by direct research, not assumed)

- **Grammar**: `dotted_ref` (`modelable.lark:280`) is `IDENT ("." IDENT)*`,
  zero version capability, used identically by `ref_type`, `source_clause`,
  `join_prefix`, `binding_model_attr`, `pinned_import`, `import_domain_stmt`.
- **Resolution**: `.target` is resolved through the canonical
  `registry/resolver.py::resolve_model_ref` in exactly **one** place today —
  `emitters/typescript.py::_collect_ref_imports` (line 82), which hardcodes
  `VersionMin(min_inclusive=1)` ("latest") since `RefType` has nowhere to
  carry an explicit version. Every other emitter (SQL, JSON Schema, C#,
  Java, Go, Rust, Python, dbt, OpenMetadata, ODCS, OpenLineage, FHIR,
  Markdown) treats `.target` as an opaque display string only — never
  resolved, never validated.
- **LSP**: `language/definition.py` (`_definition_for_unversioned_ref`,
  lines 126-136) and `language/hover.py` (`_make_unversioned_ref_hover`,
  lines 170-193) each **independently reimplement** "no version → use
  `max(domain.models[name], key=lambda v: v.version)`" via their own regex
  (`_REF_TYPE_PATTERN`) matched against raw source text — not the parsed
  IR. `language/references.py` has no `ref<>` handling at all.
- **Signature**: `compiler/render.py` already renders `ref<>` types in two
  near-duplicate places — `_render_type` (line 374, source round-trip) and
  `_render_signature_type` (line 399, canonical signature) — both currently
  just `f"ref<{target}>"`. Both call sites already have access to a version-
  spec-to-text renderer sitting right next to them:
  `_render_version_spec`/`_render_signature_version_spec` (lines 451, 463),
  already used for `source_clause`/join rendering.
- **Compatibility**: `compat/diff.py::_type_signature` (line 191, model
  fields) and C1's `_shape_type_signature` (line 227, projection fields)
  both serialize a field's *entire* type via `model_dump`/equivalent to
  detect a breaking type change. Since this includes every field of
  `RefType`, adding `.version` means **any** version-only change would
  immediately misclassify as a breaking `type_changed` — confirmed this is
  not hypothetical, it's exactly what `model_dump` would pick up.
- **Validation**: `validation/semantic.py` has no `RefType`-aware check at
  all — a `ref<>` pointing at a nonexistent domain/model/version parses and
  validates cleanly today, and silently produces wrong or missing output
  depending on which emitter reads it.

## Grammar & IR

```
ref_type: "ref" "<" dotted_ref ("@" version_spec)? ">"
```

Reuses the existing `version_spec` rule (`version_exact | version_pinned |
version_range | version_min`, already used by `source_clause`/`join_prefix`)
— **not** the separate `version_expr`/`VERSION_RANGE` mini-grammar used only
by `import_domain_stmt`, which is a distinct, less-developed syntax family.

Confirmed empirically safe by patching the actual grammar file and parsing
real `.mdl` snippets through Earley (`ambiguity="resolve"`), including the
case that looked riskiest on paper — a version range nested inside `ref<>`'s
own angle brackets, further nested inside `array<>`:

```
items: array<ref<catalog.Item @ >=1>>
```

parses with the correct tree structure (`version_min` correctly scoped
inside the inner `ref_type`, both `<`/`>` pairs correctly matched) — this is
purely additive grammar, no ambiguity in practice.

```python
class RefType(BaseModel):
    kind: Literal["ref"] = "ref"
    target: str
    version: VersionSpec | None = None  # None = unversioned/legacy
```

Reuses the existing `VersionSpec` union type (already used by
`SourceRef.version`/`JoinRef.version`) — no new version-representation type.

## Resolution

One new canonical helper (in `registry/resolver.py`, next to
`resolve_model_ref`):

```python
def resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedModelRef:
    version_spec = field_type.version if field_type.version is not None else VersionMin(min_inclusive=1)
    return resolve_model_ref(mdl, field_type.target, version_spec)
```

`VersionMin(min_inclusive=1)` — "latest matching version" — is the
documented interpretation for existing unversioned `ref<>` files. This is
not a new rule invented for this slice: it is the exact behavior
`typescript.py` already hardcodes today, and the exact behavior
`definition.py`/`hover.py` already reimplement via `max()`. This slice
centralizes it into one function all three (four, after the semantic
validation below) call into, rather than adding a fourth copy.

## Semantic validation

New check in `validation/semantic.py`, run for every `RefType` field
encountered in a model body:

- If `resolve_ref_type` raises `LookupError` (target domain/model/version
  doesn't exist): a `SEM` error. This is a real, previously-silent
  authoring mistake — today it passes `validate` cleanly and only surfaces
  as wrong or missing output at codegen time (or never, for the emitters
  that don't resolve `.target` at all).
- If `field_type.version is None` (unversioned): a non-blocking advisory
  diagnostic (new code `REF`, severity `warning`, matching the
  non-blocking-diagnostic pattern Slice B3 established for deferred syntax)
  naming the *concrete* version it resolved to — e.g. `` ref<customer.Customer>
  has no version constraint; resolved to version 3 at compile time. Add
  `@ 3` (or a version range) where durable identity matters. `` — this is
  what makes the plan's "compilation records the concrete resolved
  identity" concrete and actionable rather than a slogan with no observable
  effect.

## Compatibility classification

One shared fix point, not two: both `_type_signature` (diff.py:191) and
`_shape_type_signature` (diff.py:227) get the same `RefType`-aware special
case — when computing the signature used to detect a breaking type change,
serialize only `.target` for a `RefType`, never `.version`:

```python
def _ref_aware_signature(field_type: FieldType) -> object:
    if isinstance(field_type, RefType):
        return {"kind": "ref", "target": field_type.target}
    return field_type.model_dump(mode="json")
```

Result: pointing a `ref<>` at a *different* model is a breaking type
change (a real type change). Bumping the version a `ref<>` points at,
target unchanged, is never breaking on its own — deliberately the simple
rule, not delegating to `check_model_version_compatibility` for that
target's own breaking-ness (which C1's analogous `source_version`
dimension does for projections) — chosen for this slice specifically to
keep scope contained; revisiting this as delegation-based is a candidate
for a later slice if real-world usage shows the simple rule is too coarse.

## Signature rendering

`_render_type`/`_render_signature_type` (render.py:374, 399) both gain a
`RefType.version is not None` branch, rendering `ref<{target} @
{rendered_version}>` — reusing `_render_version_spec`/
`_render_signature_version_spec` (render.py:451, 463) respectively, the
same functions already used for `source_clause`/join rendering. No new
version-to-text logic; both existing renderers already sit next to what
they need.

## TypeScript codegen

`emitters/typescript.py::_collect_ref_imports` (line 82) changes from
unconditionally calling `resolve_model_ref(mdl, target, VersionMin(1))` to
calling the new `resolve_ref_type(field_type, mdl)` — so `ref<customer.Customer
@ 2>` imports `CustomerV2`, not whatever happens to be latest at compile
time. Unversioned refs keep exactly today's behavior (latest), since
`resolve_ref_type` falls back to `VersionMin(1)` when `.version is None`.

No other emitter changes — SQL/JSON Schema/C#/Java/Go/Rust/Python/etc. keep
treating `ref<>` as an opaque string for output purposes (e.g. SQL's `TEXT`
column, JSON Schema's `x-modelable-ref` annotation). TypeScript is the only
emitter that already does real resolution; teaching the others to do the
same is out of scope here.

## LSP consolidation

`definition.py`/`hover.py` keep their regex-based "what's under the
cursor" entry point (both work against raw/possibly-mid-edit source text,
which the parsed IR alone can't serve) — but `_REF_TYPE_PATTERN` gains an
optional `@ ...` capture group, and both files' resolution logic is
replaced with a call into a new shared helper (e.g.
`language/ref_lookup.py::resolve_ref_at_cursor` or similar — exact naming
left to the implementation plan) that wraps `resolve_ref_type`/
`resolve_model_ref`, instead of each file's own standalone `max()` call.
One implementation of "what does this ref resolve to," not three.

`language/references.py` has no `ref<>` handling today and stays that way
— out of scope, not a regression (nothing is being removed, just not
added).

## Out of scope

- Emitters other than TypeScript gaining version-aware codegen.
- `references.py` LSP support for `ref<>` targets.
- `dependency_graph.py` tracking field-level `ref<>` edges (it only tracks
  projection source/joins today) — a real, separate gap; expanding the
  dependency graph's scope is its own decision, not implied by "extend
  version resolution."
- Delegating a `ref<>` version-bump's breaking-ness to the target model's
  own compat status (C1-style) — deliberately the simpler always-non-
  breaking rule for this slice (see "Compatibility classification").

## Testing

TDD per component:
- Grammar: parse tests for all 4 forms (exact, pinned, range, min) plus
  the nested-in-`array<>` case, plus confirming unversioned `ref<>` still
  parses (`version=None`).
- `resolve_ref_type`: unversioned → latest; exact/range/pinned → correct
  resolution; unresolvable target → `LookupError`.
- Semantic validation: SEM error for unresolvable ref; `REF` warning
  (non-blocking, `validate` still exits 0) for unversioned ref, naming the
  resolved version in the message.
- Compat classification: target change → breaking `type_changed`; version-
  only change (target unchanged) → not breaking; both for model fields
  (`_type_signature`) and projection fields (`_shape_type_signature`) —
  two test files, one shared assertion shape.
- Signature rendering: round-trip test that a versioned `ref<>` renders
  with its version and re-parses identically; canonical signature changes
  when target changes, does NOT change when only version changes (this is
  the signature-side proof of the compat rule above).
- TypeScript emitter: versioned `ref<>` imports the exact version named;
  unversioned still imports latest (regression check against existing
  behavior).
- LSP: go-to-definition and hover resolve correctly for all 4 ref forms,
  including range specs; existing unversioned-ref tests still pass
  unchanged (regression check that consolidation didn't alter observable
  behavior for the case it already handled).

## Acceptance criteria (from the plan, restated as verifiable)

- `ref<>` resolution reuses the canonical source resolver
  (`resolve_ref_type` → `resolve_model_ref`, not a parallel resolution
  path).
- Resolved reference identity participates in signatures (render.py) and
  compatibility (diff.py) — verified by the signature round-trip test and
  the compat classification tests above.
- Existing (unversioned) files have a documented interpretation: `VersionMin(1)`
  ("latest"), the same rule already implicitly in effect via
  `typescript.py`/`definition.py`/`hover.py`, now centralized and paired
  with a diagnostic naming the concrete resolved version.

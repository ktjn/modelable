# Projection-to-Projection Compatibility — Design

Slice C1 from [docs/correction-and-capability-plan.md](../correction-and-capability-plan.md#slice-c1--projection-to-projection-compatibility).
Part of the Compatibility tranche (C1 → C2 → C3 → C4), unblocked now that A2
(shared dependency graph) and A3 (complete expression validation) have
landed.

## Purpose

Today, `modelable diff` and `check_model_version_compatibility()` can only
compare two versions of the same **model**. Calling them with two versions of
the same **projection** raises `LookupError: unknown model version`, because
`checker.py::_find_version` only looks up `domain.models`, never
`domain.projections` — confirmed by reading the code, not assumed. Projection
versions are first-class consumer contracts (they're what external systems
actually read), but changing one today produces no compatibility signal at
all. C1 closes that gap.

## Scope

Direct comparison of two versions of the *same* projection. Not in scope:
comparing two *different* projections, or building new IR for constructs that
don't exist in IR yet (see "Dimensions not populated" below — those are
explicitly deferred, not silently skipped).

## Entry point

Extend the existing `modelable diff <ref> <ref> --path` command and
`resolve_model_ref`-based resolution — not a new command. `resolve_model_ref`
already resolves both models and projections uniformly today
(`ResolvedModelRef.version: ModelVersion | ProjectionVersion`, via
`registry/resolver.py::_find_model_versions`, which already combines
`domain.models` and `domain.projections`). `commands/diff.py::run_diff`
currently ignores that and always calls the model-compat path unconditionally
— it needs to branch on the resolved type instead. The existing
downstream-impact block (`find_dependents`/`analyze_impact`) is already
model/projection-agnostic (it resolves through the same registry functions),
so it continues to work unchanged for projections sourced from other
projections — no new code needed there.

## Data model

New types parallel to the existing model-compat ones, not a modification of
them (`FieldChange`/`CompatibilityReport` stay model-specific — projections
have a large enough shape difference, e.g. joins, `where`, `group_by`, that
force-fitting them into the model types would be more confusing than a
parallel type):

```python
# compat/diff.py
@dataclass(frozen=True)
class ProjectionChange:
    dimension: str  # "shape" | "lineage" | "governance" | "wire" | "storage" | "source_version" | "materialisation"
    kind: str        # e.g. "field_removed", "expression_changed", "where_changed"
    breaking: bool
    field_name: str | None = None
    message: str = ""

def compare_projection_versions(
    mdl: MdlFile, old: ProjectionVersion, new: ProjectionVersion
) -> list[ProjectionChange]: ...
```

```python
# compat/checker.py
@dataclass(frozen=True)
class ProjectionCompatibilityReport:
    domain_name: str
    projection_name: str
    from_version: int
    to_version: int
    status: str  # "breaking" | "compatible" — breaking if ANY change.breaking is True
    findings: list[str] = field(default_factory=list)  # formatted, for CLI display
    changes: list[ProjectionChange] = field(default_factory=list)  # structured

def check_projection_version_compatibility(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    from_version: int,
    to_version: int,
) -> ProjectionCompatibilityReport: ...
```

Per-dimension tagging with a single overall rollup status — confirmed with
the user over per-dimension-independent statuses, to satisfy the plan's
"findings identify affected dimensions" acceptance criterion without
expanding the CLI/API status surface beyond what `report.status` callers
already expect.

## Classification rules

| Dimension | Finding | Breaking? |
|---|---|---|
| shape | field removed | yes |
| shape | field's resolved type changed | yes |
| shape | field optionality: optional → required | yes (matches the existing A1 rule in `is_optionality_breaking`) |
| shape | field added | no |
| shape | field optionality: required → optional | no |
| shape | field's resolved type becomes unresolvable (e.g. mapping changes from a resolvable direct mapping to computed) | yes |
| lineage | remapped source field/alias, or computed-field expression text changed, while output name+type+optionality are unchanged | no — always reported (never silently dropped), per the plan's "same-shape lineage changes remain visible" acceptance criterion |
| lineage | mapping kind changed (direct ↔ computed), output name unchanged | no — same treatment as other lineage changes, always visible |
| governance | access grant removed | yes |
| governance | classification level tightened (moves to a higher index in `ClassificationLevel`'s declared order: `open, internal, confidential, restricted, secret` — this enum's declaration order *is* its severity order, already relied on elsewhere in the codebase) | yes |
| governance | `@pii` annotation added to a field that didn't have it | yes |
| governance | access grant added, classification loosened, `@pii` removed | no |
| wire | an existing field's `@wire` hint *value* changes for a target already hinted in both versions | yes |
| wire | a `@wire` hint added or removed where the field had no prior hint for that target | no (can't prove a format change without a prior value to compare against) |
| storage | `where` clause text changed (added, removed, or modified) | yes |
| storage | `group_by` changed | yes |
| storage | a join added, removed, or an existing join's `cardinality`, `join_kind`, or `on` predicate changed | yes |
| source_version | the projection's own source (or a join's source) resolves to a different model version between old and new | delegates entirely to `check_model_version_compatibility()` for that model pair; this dimension's `breaking` mirrors that report's status — no independent logic, so there is exactly one implementation of "is this model version bump breaking" in the codebase |

**Stated limitation:** `where`, `on`, and computed-field expression comparisons
are text-based (string inequality), not semantic. A CEL expression rewritten
to the same effect (reordered clauses, added whitespace) will be reported as
"changed" even though behavior is identical. This is a conservative default,
consistent with how the rest of the compiler treats CEL expressions as opaque
text outside of the validator — not a gap to close in this PR.

## Dimensions this PR does not populate

Both are genuine IR gaps, not omissions — each is already documented
elsewhere in the codebase, and this PR adds one more callout for each:

- **materialisation**: `materialisation {}` blocks have no IR field at all
  (Slice B3 confirmed the grammar rule is parsed and discarded before IR
  construction; the compiler only emits a `DEFERRED` diagnostic warning when
  one is used). There is nothing to compare. `ProjectionChange.dimension`
  includes `"materialisation"` as a valid value in the type for when this
  changes, but no code path produces one yet.
- **event operation coverage**: `AutoProjectionTarget.operations` exists only
  on the pre-expansion `auto projections { event { operations: [...] } }`
  declaration (`parser/ir.py:429`) and is discarded during expansion —
  `compiler/render.py:270-271` is the only reader, for canonical-format
  round-tripping, the same shape of gap as the `generate_targets`/B3 findings.
  It is not present on the resulting `ProjectionVersion` to diff. Comparing
  it would mean either new IR plumbing to retain it through expansion, or a
  wholly separate declaration-level comparison — both out of scope for this
  PR. Recorded as a `capabilities.py` `deferred_features` entry instead.

## New shared utility

`_resolve_projection_field_type` is duplicated across 5 files today
(`emitters/dbt_yaml.py`, `emitters/json_schema.py`, `emitters/protobuf.py`,
`emitters/typescript.py`, `validation/semantic.py`) — confirmed by grep, not
assumed. None of them resolve field *optionality*, which the shape dimension
needs (a projection field has no `optional` flag of its own; it's inherited
from whichever source field a direct mapping points at, or is unknown for a
computed mapping). Rather than write a 6th duplicate:

- New `compat/projection_fields.py`: `resolve_projection_field_type_and_optionality(field, projection, mdl) -> tuple[FieldType | None, bool | None]`, modeled on `validation/semantic.py::_resolve_projection_field_type` (the most complete of the 5 — it's the only one that resolves through `projection.joins`, not just the primary `projection.source`), extended to also resolve optionality from the same source field.
- The 5 existing duplicates are **not** touched or consolidated in this PR — each has emitter-specific output shape concerns (JSON Schema types, protobuf wire numbering, TypeScript types) that aren't identical to what compat needs, and unifying them is a separate, independently-scoped cleanup. Not proposing it here to stay focused on what C1 needs.

## Error handling

- Comparing a projection ref against a model ref (or vice versa) with the
  same domain+name — not possible in practice (models and projections share
  one namespace per domain per `_find_model_versions`, so a ref can only
  resolve to one kind), but `run_diff` will assert this defensively rather
  than silently miscompare.
- Unresolvable source/join versions inside `compare_projection_versions`
  (e.g. a dangling reference) surface as a `LookupError`, consistent with
  how `resolve_model_ref` and the existing model-compat path already fail.

## Testing

TDD, one RED/GREEN pair per classification-rule row above, in a new
`cli/tests/test_projection_compatibility.py`. Plus:

- A `commands/diff.py`-level CLI test proving `modelable diff
  domain.Proj@1 domain.Proj@2` now succeeds instead of raising
  `LookupError: unknown model version`.
- A source-version delegation test: two projection versions pinning
  breaking vs. compatible model version pairs, proving the `source_version`
  dimension's `breaking` value matches `check_model_version_compatibility`'s
  own status for that pair.
- A `capabilities.py` `deferred_features` entry + test for
  `projection-event-operation-coverage-compatibility`, following the same
  pattern as the Slice B3 deferred-construct entries.
- Full regression sweep: `pytest`, `ruff`, mypy baseline ratchet, coverage
  ratchet, `mkdocs build --strict` (this doc + any language-reference
  updates).

## Acceptance criteria (from the plan, restated as verifiable)

- `modelable diff` succeeds for two projection versions of the same
  projection (previously: `LookupError`).
- A lineage-only change (remapped source field, same output shape) appears
  in `findings` and is tagged `dimension="lineage"`, `breaking=False` — it is
  never silently dropped.
- Every finding's `ProjectionChange.dimension` identifies which of shape /
  lineage / governance / wire / storage / source_version it affects.
- `report.status == "breaking"` if and only if at least one change has
  `breaking=True`.

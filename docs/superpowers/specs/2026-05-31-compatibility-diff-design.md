# Compatibility Diff Design

**Date:** 2026-05-31  
**Status:** Draft for review  
**Scope:** Single-domain published model-version compatibility comparison and `modelable diff`

## Goal

Add a deterministic compatibility engine that compares two published model versions in the same domain and surfaces the result through `modelable diff`.

## Non-Goals

- Cross-domain dependency traversal.
- Projection compatibility impact analysis.
- Registry-wide impact simulation.
- Governance finding generation beyond the compatibility status and field-change findings already needed for `diff`.
- Automatic version migration or rewrite.

## Context

The repository already has a basic compatibility comparison path:

- `cli/src/modelable/compat/diff.py` classifies field-level changes between two `ModelVersion` objects.
- `cli/src/modelable/compat/checker.py` wraps those changes in a compatibility report.
- `cli/src/modelable/commands/diff.py` resolves the refs, checks same-domain/same-model identity, and prints a minimal report.
- `cli/tests/test_compatibility.py` already covers field removal, rename, nullability, type, enum, and identity changes for model versions.
- `cli/tests/test_cli.py` already covers the CLI entry point for `diff`.

The gap is not starting from scratch. The gap is making the compatibility slice explicit, well-bounded, and testable as a first Milestone 4 step:

- keep the engine single-domain,
- keep the comparison model-version focused,
- and make the CLI output deterministic and more explicit about what is being compared.

## Recommended Approach

Keep the first slice narrow:

- Compare one published model version to another published model version.
- Require both refs to resolve to the same domain and model name.
- Use the existing field-change classifier as the compatibility engine.
- Surface the report via `modelable diff`.

### Why this approach

- It preserves the current compatibility boundary and avoids conflating model comparison with projection impact analysis.
- It keeps the first slice useful immediately for version review without requiring planner or registry changes.
- It leaves projection compatibility for a later slice where cross-model dependency handling can be designed explicitly.

### Alternatives considered

| Approach | Trade-off | Decision |
|---|---|---|
| Model-version only | Smallest useful slice, clean boundary, low risk. | Chosen. |
| Model + projection compatibility | More user value, but introduces dependency traversal and more policy decisions. | Deferred. |
| Full registry impact analysis | Broadest result, but too much coupling for the first Milestone 4 slice. | Rejected for now. |

## Architecture

### Engine

`cli/src/modelable/compat/diff.py`

- Compare two `ModelVersion` values field by field.
- Emit deterministic `FieldChange` records for:
  - removed field
  - added field
  - renamed field
  - nullability change
  - identity change
  - enum change
  - type change
- Preserve a stable change order so CLI output and tests remain predictable.

`cli/src/modelable/compat/checker.py`

- Resolve compatibility status for one domain and one model.
- Classify the report as `compatible` or `breaking`.
- Treat additive changes as breaking only when they introduce incompatible field changes such as removal, rename, required-field addition, identity change, type change, or enum change.
- Keep the report format simple enough for the CLI to print directly.

### CLI

`cli/src/modelable/commands/diff.py`

- Parse the two refs.
- Reject refs that do not refer to the same domain and model.
- Resolve each ref to a concrete published version.
- Call the compatibility checker.
- Print:
  - the compared refs
  - the overall compatibility status
  - one line per field change
- Exit nonzero when the result is breaking.

## Output Contract

The first slice should produce deterministic output that can be read by a human and asserted in tests.

Recommended output shape:

```text
customer.Customer@1 -> customer.Customer@2
status: breaking
- removed_field name
- added_field email
```

The exact wording of individual findings should remain stable across runs. The command should not print extra narrative text beyond the report fields and findings.

## Validation Rules

- The refs must belong to the same domain and model.
- The resolved versions must exist in the workspace.
- The report must be deterministic for the same input workspace and refs.
- A required field addition counts as breaking.
- A breaking model declaration can still be intentionally marked breaking, but the report must still show the field-level findings.

## Testing Strategy

### Unit tests

Extend `cli/tests/test_compatibility.py` with focused coverage for:

- required field addition as breaking
- optional field addition as compatible
- rename detection
- nullability changes
- type changes
- enum changes
- identity changes
- same-version or same-field no-op reporting

### CLI tests

Extend `cli/tests/test_cli.py` with `diff` command coverage for:

- compatible comparison output
- breaking comparison output
- same-domain enforcement
- deterministic report text
- pinned version and version-range resolution if those are already supported by the existing resolver

### Local gate

For the first slice, run:

```text
cd cli
uv sync --extra dev
uv run pytest tests/test_compatibility.py tests/test_cli.py -v
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp --strict
```

Then review the diff and confirm the output stays deterministic.

## Repository Changes Needed

The first implementation slice should touch:

- `cli/src/modelable/compat/diff.py`
- `cli/src/modelable/compat/checker.py`
- `cli/src/modelable/commands/diff.py`
- `cli/tests/test_compatibility.py`
- `cli/tests/test_cli.py`
- `docs/cli-spec.md` if the command wording needs to be made more explicit
- `docs/mvp-implementation-plan.md` if the milestone checklist should be reconciled after the slice lands

Avoid dragging in governance, planner, or registry changes until the compatibility core and CLI report shape are stable.

## Risks

- If the report format is underspecified, future slices will have to preserve accidental wording.
- If same-domain enforcement is too strict or too loose, the CLI can become confusing for version review.
- If the change classifier order shifts, test assertions may become flaky unless the output order is explicitly stabilized.

## Success Criteria

This design is complete when:

- `modelable diff` compares two published model versions in one domain,
- breaking changes are reported deterministically,
- the comparison is tested at both engine and CLI levels,
- and the output is explicit enough to serve as the basis for the later projection and governance slices.

# Slice B3 — deferred-syntax diagnostics

Scope confirmed with user 2026-08-05:

- The 6 dead workspace/federation constructs (`registry {}`, `peers: [...]`,
  `consumer {}`, `subscription {}` both forms, `materialisation {}`) get a
  **non-blocking warning diagnostic** (new code `DEFERRED`), not a redesigned
  IR representation and not a hard error. `validate`/`--strict` keep exiting 0
  for existing sample scenarios that use them.
- The opaque catch-all inside `binding {}` blocks (unrecognized keys beyond
  `adapter`/`model`/`table`) gets the same treatment.
- Follow-up: add roadmap/plan pointers so these constructs get a real design
  pass later instead of staying silently deferred forever.

## Why not IR representation or hard-error rejection

- Full IR representation is federation/runtime design work disproportionate
  to one slice (registry/peers imply a federation model; subscriptions/
  materialisation imply a runtime model — none of that exists yet).
- Hard-error rejection breaks curated sample scenarios (03, 06, 07, 08) that
  demonstrate these patterns and are asserted to validate cleanly in
  `test_samples.py` (`test_all_scenarios_sem_errors_are_known`,
  `test_ecommerce_scenario_...`, `test_partner_marketplace_scenario_...`).
  Fixing that up is out of proportion for a diagnostics-only slice.
- Diagnostic-only satisfies all 3 acceptance criteria in
  `docs/correction-and-capability-plan.md` Slice B3: "never silently
  discarded", "explicit diagnostic", "canonical rendering cannot erase
  unhandled declarations" (rendering was never touched, so nothing to fix
  there for these 6 — only `generate_targets`, already bucket b, round-trips).

## Design

New module `cli/src/modelable/validation/deferred_syntax.py`:

```python
def find_deferred_syntax_diagnostics(tree: Tree, path: str) -> list[Diagnostic]
```

Walks the **raw pre-transform Lark tree** (not the IR) for 6 rule names via
`tree.find_data(...)`, one warning `Diagnostic` per occurrence, plus a
targeted walk of `binding_decl` nodes for opaque `binding_item` children
(only the immediate `ignored_block_item` alternative, not nested content —
so registry/consumer's own opaque bodies aren't double-counted).

Chosen over adding transformer methods + new IR fields: zero changes to
`parser/transformer.py`, `parser/ir.py`, or `compiler/render.py` — the
smallest possible footprint for "diagnose only" scope, and avoids
transformer/IR churn that assembly methods (`workspace_decl`,
`projection_decl`, `start`) would otherwise need to filter for.

No line/column: consistent with every other SEM/CEL diagnostic in this
codebase today (none populate `Diagnostic.line/column`), so this doesn't
introduce a new precedent the rest of the diagnostics don't follow.

### Parse-tree plumbing

`parser/parse.py` gains `parse_text_to_ir_with_tree()` returning
`(MdlFile, Tree)` from a single parse; `parse_text_to_ir()` becomes a thin
wrapper discarding the tree. Avoids double-parsing every source file.

### Workspace wiring

`WorkspaceSource` and `Workspace` (`compiler/workspace.py`) gain a
`warnings: list[Diagnostic]` field, populated alongside `errors` in
`load_workspace_from_sources`. Deliberately **not** merged into `.errors` —
every existing consumer of `.errors` (CLI compile, registry index, LSP,
LLM workspace editor/query, browser api) treats that list as blocking;
keeping warnings in a separate field means none of those call sites need to
change, and none of them regress.

`commands/common.py::load_workspace_or_exit` prints `.warnings` as
`[yellow]WARNING[/yellow]` after the existing error handling, without
affecting the exit code — this is the one new consumer, and the only one
this slice adds.

### Capability manifest

Add 6 new `deferred_features` entries to `cli/src/modelable/capabilities.py`
so `modelable capabilities` documents these constructs by the same
vocabulary B1 established, and the new diagnostic messages can point users
at `modelable capabilities` for authoritative status.

## Tasks

1. `validation/deferred_syntax.py` RED/GREEN: unit tests per construct
   (registry, peers, consumer, subscription_block, subscription_decl,
   materialisation_block, binding opaque content) using `parse_text`.
2. `parse.py` refactor: `parse_text_to_ir_with_tree`, keep `parse_text_to_ir`
   behavior-identical (regression covered by full existing suite).
3. `compiler/workspace.py` wiring: `.warnings` field + population; test that
   a file combining several deferred constructs produces warnings but empty
   `.errors`.
4. `commands/common.py` CLI wiring: `modelable validate` prints warnings,
   exit code stays 0; CLI-level test.
5. `capabilities.py`: 6 new deferred_features entries; extend
   `test_capabilities.py`.
6. Roadmap follow-up: update `ROADMAP.md` "Outside the near-term compiler
   roadmap" section and `docs/correction-and-capability-plan.md` Slice B3
   with explicit next-step pointers for each construct (design pass required
   before promotion out of deferred).
7. Full regression: pytest, ruff, mypy baseline, mkdocs --strict (docs
   touched), browser wheel packaging test.

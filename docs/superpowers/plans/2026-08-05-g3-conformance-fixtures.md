# Slice G3 — conformance fixtures (first tranche)

Scope confirmed with user 2026-08-05: extend the existing shared conformance
pipeline, not build shared fixtures across all 7 named areas from scratch.

## Why not the full scope as written

Research found only one working cross-system shared-fixture pipeline in the
repo: `cli/tests/conformance/browser/` — native generates a snapshot,
`web/scripts/vendor-python-assets.mjs` vendors it, `web/tests/conformance.spec.ts`
asserts the Pyodide browser compiler against the same JSON. It covers 5
scenarios, none of which are composite-keys or the B3 deferred constructs —
the two cases the plan calls out by name ("especially composite keys and
deferred constructs"). LSP, compatibility, and signature tests have zero
shared-fixture infrastructure and no generator script; building all of that
in one slice is a multi-week infra project, disproportionate to how B1–B3
were scoped. This PR extends the one pipeline that already works.

## What shipped

- Two new fixtures: `composite-key.mdl` (two `@key` fields → SEM error) and
  `deferred-constructs.mdl` (a `materialisation {}` block → DEFERRED warning,
  from Slice B3).
- Wired into `write_browser_conformance.py::SCENARIOS`,
  `test_browser_conformance.py::SNAPSHOT_NAMES`, generated checked-in
  snapshots, `vendor-python-assets.mjs::BROWSER_CONFORMANCE_SCENARIOS` (+ its
  own unit test's synthetic fixture list), and `conformance.spec.ts::scenarios`.
- Verified for real: built the browser wheel, ran the full vendoring
  pipeline, built the web app, and ran `conformance.spec.ts` against actual
  Chromium + Pyodide — not just the native snapshot-generation test. The
  Pyodide browser compiler produces byte-identical diagnostics to native for
  both new scenarios.

## Bug found and fixed along the way

`language/workspace.py::LanguageWorkspace.synchronize` — the method backing
the browser's `open_workspace` and, by extension, the whole editor
diagnostics surface (Playground, and any future LSP consumer built on this
layer) — only read `workspace.errors`, never `workspace.warnings`. This
meant Slice B3's DEFERRED warnings were visible in `modelable validate` but
invisible in the browser/Playground. Without this fix, the deferred-
constructs conformance scenario would have encoded "browser shows nothing"
as the expected snapshot — technically passing, but silently documenting a
real gap instead of closing it. Fixed with a RED/GREEN test
(`test_synchronize_includes_deferred_syntax_warnings_in_diagnostics`) before
writing the fixture.

Deliberately not touched: `browser/api.py::compile()`'s diagnostics (still
errors-only — compile-blocking diagnostics were never meant to include
non-blocking warnings, and neither new scenario needs a `compile` snapshot
key), and `lsp/server.py` (the VS Code extension's LSP surface is a
different code path from `browser/api.py`; wiring warnings into published
LSP diagnostics is a separate, out-of-scope change).

## Deferred to a later G3 tranche

Per the plan's full scope: LSP unit-test fixture sharing (30 files, no
generator today), compatibility test fixtures, signature test fixtures, and
machine-checkable linkage from `capabilities.py` entries to the tests that
verify them (considered as an option, not chosen for this PR — see the
"capability manifest" alternative that was offered and not picked).

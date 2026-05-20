# LSP Gaps — Design Spec

**Date:** 2026-05-20
**Scope:** Four bug fixes and three new LSP capabilities for the Modelable language server.

---

## Background

The LSP recently gained support for projection-sourced projections across definition, hover, and references. Several gaps remain: completion and rename missed the same fix, document symbols omit projection fields, and three common LSP capabilities (documentHighlight, foldingRange, inlayHint) are unregistered.

---

## Bug Fixes

### 1. `completion.py` — alias field completion broken for projection sources

**File:** `cli/src/modelable/lsp/completion.py`
**Function:** `_mirror_or_workspace_fields`

After `domain.models.get(model_name)` returns nothing, also check `domain.projections.get(model_name)`. One extra fallback branch before falling back to `mirror_field_names`.

### 2. `rename.py` — declaration lookup uses `"model"` kind only

**File:** `cli/src/modelable/lsp/rename.py`
**Function:** `_add_model_field_renames`

`_find_field_location` is called with `kind="model"` hardcoded. Add a `_find_source_field_location` helper (same pattern as `references.py`) that tries `"model"` then `"projection"`, and call it instead.

### 3. `rename.py` — projection field rename misses downstream usages

**File:** `cli/src/modelable/lsp/rename.py`
**Function:** `_add_projection_field_renames`

Currently only renames the declaration. Add the same projection-field-reference scan present in `_add_model_field_renames`: iterate workspace sources, build alias maps per projection block, find `alias.field` references resolving to this projection field, emit `TextEdit` entries.

### 4. `document_symbols.py` — projection fields invisible in outline

**File:** `cli/src/modelable/lsp/document_symbols.py`
**Function:** `build_document_symbols`

The field scan only matches `_FIELD_PATTERN` (`name?: type`). Add a fallback match against `_PROJECTION_FIELD_PATTERN` (`name <-` / `name =`) so projection field children appear in the symbol tree.

---

## New Feature: `textDocument/documentHighlight`

**New file:** `cli/src/modelable/lsp/highlight.py`

Reuses the same symbol-resolution logic as `references.py` but restricts results to the **current document URI only**. Returns `DocumentHighlight` objects:
- `DocumentHighlightKind.Write` for the declaration location
- `DocumentHighlightKind.Read` for each usage location

Registered in `server.py` under `TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT`. Declared in `initialize` capabilities as `document_highlight_provider=True`.

---

## New Feature: `textDocument/foldingRange`

**New file:** `cli/src/modelable/lsp/folding.py`

Scans the document line by line tracking brace depth. Each `{` at depth 0→1 records a start line; the matching `}` at depth 1→0 gives the end. Returns one `FoldingRange` per block (domains, models, projections). Kind: `FoldingRangeKind.Region`.

Registered in `server.py` under `TEXT_DOCUMENT_FOLDING_RANGE`. Declared in `initialize` as `folding_range_provider=True`.

---

## New Feature: `textDocument/inlayHint`

**New file:** `cli/src/modelable/lsp/inlay_hints.py`

Two hint types, both resolved against the compiled workspace model:

**Field source type:** For each projection field line (`name <- alias.field` or `name = expr`), resolve the source field's type via the alias map and emit a hint `": type"` positioned immediately after the field name. Skip computed expressions where the type cannot be determined from the alias map alone.

**Model kind:** For each `from`/`join` source line, resolve the referenced model or projection and emit a hint `"[entity]"`, `"[aggregate]"`, `"[event]"`, `"[value]"`, or `"[projection]"` positioned after the version number.

Registered in `server.py` under `TEXT_DOCUMENT_INLAY_HINT`. Declared in `initialize` as `inlay_hint_provider=types.InlayHintOptions(resolve_provider=False)`.

---

## Testing

Each bug fix gets a regression test in the relevant existing test file. Each new feature gets a new test file:
- `tests/test_lsp_highlight.py`
- `tests/test_lsp_folding.py`
- `tests/test_lsp_inlay_hints.py`

All tests use `LspWorkspaceIndex` with inline `.mdl` text, no mocks.

---

## Files Changed

| File | Change |
|------|--------|
| `lsp/completion.py` | Bug fix: projection field lookup |
| `lsp/rename.py` | Bug fix: source field location + downstream rename |
| `lsp/document_symbols.py` | Bug fix: projection fields in outline |
| `lsp/highlight.py` | New: documentHighlight |
| `lsp/folding.py` | New: foldingRange |
| `lsp/inlay_hints.py` | New: inlayHint |
| `lsp/server.py` | Register new capabilities |
| `tests/test_lsp_highlight.py` | New tests |
| `tests/test_lsp_folding.py` | New tests |
| `tests/test_lsp_inlay_hints.py` | New tests |
| `tests/test_lsp_definition.py` | Existing (no change) |
| `tests/test_lsp_hover.py` | Existing (no change) |
| `tests/test_lsp_references.py` | Existing (no change) |

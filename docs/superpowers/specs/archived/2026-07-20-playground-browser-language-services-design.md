# 2026-07-20 Playground Browser Language Services — Design

## Status

Accepted on 2026-07-20.

Execution is broken into reviewable tasks in the
[Playground Browser Language Services implementation plan](../../plans/archived/2026-07-20-playground-browser-language-services.md).

This specification defines Phase 3b of the
[Modelable Playground architecture](../../playground-design.md). It builds on
the shipped
[workspace and persistence foundation](archived/2026-07-20-playground-workspace-persistence-design.md)
and provides browser-native language features without running the desktop LSP
transport in the browser.

The repository [roadmap](../../../ROADMAP.md) makes browser-native language
services the active Playground slice. Completion, hover, definition,
references, rename, and live diagnostics must operate over the durable
multi-file workspace before visualization, analysis, or local AI depend on
editor semantics.

## Context

The deployed Playground now owns one versioned local workspace containing
normalized `.mdl` files. React and Monaco retain stable file models, IndexedDB
restores source and active selection, and the browser compiler receives sorted
workspace snapshots through a same-origin Pyodide worker.

The desktop language server already implements completion, hover, definition,
references, prepare-rename, and rename. Those builders are coupled to
`lsprotocol` response types and an LSP workspace index that includes
filesystem and federation behavior. Calling them directly from the browser
would make the browser compiler depend on a desktop transport contract and
would preserve assumptions that do not apply to the static Playground.

Reimplementing the same semantics in TypeScript would instead create two
language implementations. Completion ordering, symbol resolution, reference
identity, and rename edits would drift between the CLI/VS Code and browser
surfaces.

Phase 3b therefore extracts Modelable-owned language semantics behind neutral
DTOs. The desktop LSP and browser compiler become adapters over the same core.

## Goals

- Provide debounced live diagnostics over the complete browser workspace.
- Provide completion and hover while a document is temporarily invalid.
- Provide cross-file definition and reference navigation.
- Provide Monaco-native prepare-rename and atomic cross-file rename.
- Keep desktop and browser language semantics on one shared Python
  implementation.
- Keep the browser transport independent of `pygls` and `lsprotocol`.
- Reject stale results and workspace edits using exact workspace and file
  revisions.
- Preserve the Playground's local-only privacy, CSP, accessibility, and
  bounded-layout guarantees.
- Deliver completion/hover first, then navigation/references/rename.

## Non-goals

- Running the desktop LSP server or JSON-RPC transport inside Pyodide.
- Reimplementing Modelable language semantics in TypeScript.
- Renaming domains, semantic types, workspace files, registry mirrors, or
  federated symbols.
- Providing registry-backed or remote completion candidates.
- Adding quick fixes, code actions, document symbols, workspace symbols,
  folding, or semantic tokens.
- Adding recovery parsing or a new error-tolerant parser.
- Persisting diagnostics, semantic indexes, completion results, hover content,
  locations, or rename edits.
- Changing the visualization, analysis, WebLLM, service-worker, or extension
  phases.
- Changing the static, same-origin deployment model.

## Decisions

### 1. Extract a protocol-neutral language core

Create a focused `modelable.language` package. It owns:

- a workspace index containing current documents and the last parseable
  semantic workspace;
- symbol and cursor-context resolution;
- completion, hover, definition, references, prepare-rename, and rename;
- Modelable-owned positions, ranges, locations, completion items, hover
  content, and text edits; and
- validation of identifiers, collisions, revision expectations, and edit
  overlap.

The package must not import `pygls` or `lsprotocol`. It may reuse the parser,
compiler workspace loader, registry resolver, summaries, and diagnostic model.

The existing `modelable.lsp` handlers convert neutral results into LSP types.
The browser adapter converts the same results into browser DTOs. Desktop
behavior remains the compatibility baseline unless this specification
explicitly narrows browser scope.

### 2. Use one current-document set and one last-parseable snapshot

The language workspace stores:

```python
@dataclass(frozen=True)
class LanguageDocument:
    uri: str
    text: str
    version: int
    content_hash: str

@dataclass
class LanguageWorkspace:
    revision: int
    documents: dict[str, LanguageDocument]
    semantic_revision: int | None
    semantic_hashes: dict[str, str]
    workspace: Workspace | None
```

Every synchronization replaces the current document set with the exact sorted
browser snapshot. When the complete workspace parses, it also replaces the
semantic workspace, semantic revision, and semantic hashes.

When current text does not parse:

- current documents and parse diagnostics still advance;
- the previous parseable semantic workspace remains available;
- completion may combine current cursor text with last-known semantics;
- hover may use last-known semantic information when the symbol resolves;
- definition and references omit locations in files whose current content
  hash differs from the semantic snapshot; and
- rename is unavailable until the exact current revision parses.

"Parseable" does not mean free of semantic diagnostics. A workspace with a
complete IR remains useful for navigation and language results while its
validation diagnostics are displayed.

### 3. Introduce browser compiler protocol version 2

Protocol version 2 retains initialization, formatting, and JSON Schema
compilation and adds a revisioned language-service contract:

```ts
type BrowserCompilerMethod =
  | "runtime.initialize"
  | "workspace.open"
  | "source.format"
  | "compile.jsonSchema"
  | "language.completion"
  | "language.hover"
  | "language.definition"
  | "language.references"
  | "language.prepareRename"
  | "language.rename";

interface BrowserWorkspaceOpen {
  workspaceRevision: number;
  sources: BrowserSource[];
}

interface BrowserLanguagePosition {
  workspaceRevision: number;
  uri: string;
  line: number;
  character: number;
}
```

Lines and characters are zero-based UTF-16 positions at the TypeScript
boundary, matching Monaco and LSP. Python conversion is explicit and tested.

`workspace.open` is the only operation that replaces worker language state.
It returns the accepted revision, current diagnostics, and source hashes.
Language requests name the exact expected revision and never carry hidden
filesystem state.

Typed non-terminal language errors include:

- `STALE_WORKSPACE` when the worker does not own the requested revision;
- `LANGUAGE_UNAVAILABLE` when no usable semantic snapshot exists;
- `INVALID_POSITION` for an invalid URI or cursor;
- `INVALID_RENAME` for an invalid name, collision, or unsupported symbol; and
- `STALE_EDIT` when affected source hashes do not match.

Malformed envelopes and terminal worker failures continue using the existing
compiler error handling.

### 4. Coordinate synchronization in TypeScript

A `BrowserLanguageServiceController` sits between React/Monaco and
`BrowserCompilerClient`.

It:

- observes immutable `PlaygroundWorkspace` snapshots;
- debounces background synchronization by 300 ms;
- ensures a provider's captured revision is synchronized before its request;
- allows one `workspace.open` request in flight;
- coalesces queued work to the newest snapshot;
- records the newest accepted worker revision;
- cancels or ignores stale provider results; and
- exposes retry/disposal behavior consistent with the compiler client.

Explicit Validate remains available. It uses the synchronized current
workspace and the same diagnostics contract. Compilation and formatting keep
their current UI behavior.

Provider requests that arrive before the diagnostic debounce expires force
synchronization of their captured revision. A newer edit may supersede that
request; older synchronization or provider completions never make the UI
current.

### 5. Apply language results through Monaco adapters

Register Monaco providers for the Modelable language ID:

- completion item provider;
- hover provider;
- definition provider;
- reference provider; and
- rename provider with prepare-rename support.

Adapters convert neutral browser DTOs into Monaco types only. They contain no
Modelable symbol-resolution rules.

Definition navigation selects the target workspace file, activates its stable
Monaco model, restores in-session view state, reveals the exact range, and
focuses the editor.

Reference results are sorted by URI and range. Monaco owns the visible
reference UI.

Rename uses Monaco's standard rename input and preview. The worker returns
sorted edits grouped by normalized workspace URI plus the expected file
versions and hashes. Before applying them, the controller verifies:

- the workspace revision is unchanged;
- every target file still exists;
- every version and hash matches;
- no edits overlap; and
- every URI belongs to the current `.mdl` workspace.

The controller applies one Monaco workspace edit. All changes are one logical,
undoable operation and then flow through the existing workspace mutation and
persistence boundaries.

## Neutral DTO contract

The neutral core defines small immutable types equivalent to:

```python
@dataclass(frozen=True, order=True)
class LanguagePosition:
    line: int
    character: int

@dataclass(frozen=True)
class LanguageRange:
    start: LanguagePosition
    end: LanguagePosition

@dataclass(frozen=True)
class LanguageLocation:
    uri: str
    range: LanguageRange

@dataclass(frozen=True)
class LanguageCompletion:
    label: str
    kind: str | None
    sort_text: str
    detail: str | None = None
    documentation: str | None = None
    replacement: LanguageRange | None = None

@dataclass(frozen=True)
class LanguageHover:
    markdown: str
    range: LanguageRange | None

@dataclass(frozen=True)
class LanguageTextEdit:
    uri: str
    range: LanguageRange
    new_text: str
    expected_version: int
    expected_hash: str
```

Completion kinds use a Modelable-owned closed string vocabulary. Each adapter
maps that vocabulary explicitly rather than exposing numeric LSP or Monaco
enums.

Hover Markdown is plain CommonMark generated by Modelable. It contains no raw
HTML, command links, images, or trusted content flag.

## Feature behavior

### Live diagnostics

Every accepted workspace synchronization returns parse and semantic
diagnostics for current text. React clears diagnostics only when a newer
revision begins synchronization or an exact newer result is accepted.

The status surface distinguishes:

- language synchronization in progress;
- diagnostics current for the workspace;
- compiler/language worker unavailable; and
- persistence state.

Diagnostics stay derived and are not persisted.

### Completion

Browser completion matches the desktop language service for local:

- keywords and annotations;
- domain declarations;
- entity, aggregate, event, value, and projection declarations;
- model and projection versions;
- projection source aliases; and
- model and projection fields.

Labels, kinds, sort order, filter behavior, and replacement ranges are
deterministic. Registry mirrors, federation candidates, and remote results are
excluded.

Completion returns an empty result rather than an error when no candidate is
available. Expected stale results are silent in the UI.

### Hover

Hover may describe:

- canonical domain/name/version identity;
- declaration kind;
- field type and optionality;
- key, PII, classification, and deprecation metadata; and
- projection source or mapping information.

Last-known semantic hover is allowed during a parse error only when the cursor
symbol resolves against current text and the result cannot navigate or mutate
source.

### Definition and references

Definition and references cover the same local symbol set as the current
desktop implementation:

- entity, aggregate, event, value, and projection declarations;
- versioned and unversioned local references;
- source fields;
- projection fields; and
- projection alias field references.

Locations in changed files are omitted while the current workspace is not
parseable. Results never point to disk, registry, or a URI outside the browser
workspace.

### Rename

Prepare-rename returns the exact editable identifier range or rejects the
symbol.

Rename supports local model/projection declarations and their fields, matching
desktop behavior. It excludes domains, semantic types, files, mirrors, and
federated symbols.

The new name must be a valid Modelable identifier and must not collide in the
target scope. The current workspace must be parseable at the exact requested
revision. Every declaration and reference edit is returned together or no edit
is returned.

## Delivery

### Batch A — shared core, synchronization, diagnostics, completion, hover

Batch A:

1. introduces neutral DTOs and the current/last-parseable workspace index;
2. adapts desktop completion and hover to the neutral core;
3. introduces browser protocol v2 and worker state;
4. adds the TypeScript synchronization controller;
5. adds debounced live diagnostics;
6. registers Monaco completion and hover providers; and
7. ships independently with conformance and performance coverage.

### Batch B — definition, references, rename

Batch B:

1. adapts desktop definition, references, and rename to the neutral core;
2. adds the remaining protocol v2 methods;
3. registers Monaco definition, references, and rename providers;
4. adds atomic revision/hash-checked workspace edit application; and
5. completes Phase 3b acceptance and documentation.

The top-level Phase 3b spec remains active between batches. It is archived only
after Batch B merges and all completion criteria pass.

## Error handling

- Expected stale synchronization and provider results are discarded silently.
- Invalid cursor positions and unsupported rename targets return typed
  non-terminal errors.
- A parse failure returns diagnostics and retains the last parseable semantic
  snapshot.
- A semantic diagnostic does not destroy a parseable snapshot.
- A failed background synchronization leaves the editor usable and exposes a
  retryable language-service status.
- A terminal worker failure uses the existing compiler retry action and
  rebuilds language state from the current in-memory workspace.
- A rename precondition failure changes no file.
- Persistence failures do not disable language services; changes remain
  memory-only under the existing persistence contract.

No error message or log includes source text, hover content, symbol names,
completion labels, cursor context, or edit text.

## Security and privacy

- All source and language processing remains in the same-origin worker.
- No request is sent to a remote provider or registry.
- Hover Markdown is rendered as untrusted Markdown with raw HTML disabled.
- Browser DTO validation rejects unknown fields, invalid ranges, invalid URIs,
  duplicate edits, and out-of-workspace targets.
- Rename can modify only files already present in the normalized `.mdl`
  workspace.
- Diagnostics, results, semantic indexes, and edits are not persisted.
- Test-only inspection hooks remain gated by `?test=1`.
- CSP keeps `script-src` same-origin apart from the existing Pyodide WebAssembly
  requirement.

## Accessibility and UX

- Completion, hover, navigation, references, and rename remain operable through
  Monaco keyboard commands.
- Language synchronization and failure state use concise polite live regions.
- Diagnostic errors keep their existing assertive behavior where appropriate.
- Provider cancellation does not produce noisy announcements.
- Navigation changes the active file visibly and restores focus.
- Rename uses Monaco's standard accessible input and preview behavior.
- The file rail and editor retain their existing bounded desktop and
  horizontally safe mobile layouts.

## Performance budgets

Measure warm-worker medians over representative local multi-file fixtures:

- completion: at most 100 ms;
- hover: at most 100 ms;
- definition: at most 150 ms;
- references: at most 150 ms;
- prepare-rename: at most 250 ms; and
- rename: at most 250 ms.

The fixture must contain cross-file model and field references and enough
symbols to exercise deterministic sorting. Measurements exclude cold Pyodide
initialization but include worker messaging, Python DTO conversion, and
TypeScript response validation.

Existing cold/cached initialization, validation, compilation, application
bundle, Modelable wheel, additional Python, and Monaco reporting budgets remain
unchanged.

## Testing

### Neutral core

- DTO validation and deterministic ordering.
- Current-document and last-parseable snapshot transitions.
- Desktop-parity completion, hover, definition, references, and rename.
- Temporarily invalid text behavior.
- Identifier and collision rejection.
- Cross-file edit completeness, ordering, hashes, and overlap rejection.

### Adapters and protocol

- Neutral-to-LSP conversion preserves existing desktop results.
- Neutral-to-browser conversion uses exact zero-based UTF-16 ranges.
- Protocol v2 rejects v1 language methods, malformed DTOs, unknown fields,
  invalid revisions, and invalid URIs.
- Worker state accepts only complete sorted snapshots and rejects stale
  language requests.
- Native and browser results match shared cross-file fixtures.

### TypeScript and Monaco

- Debounce, forced synchronization, request coalescing, and stale-result
  suppression.
- Provider registration and disposal.
- Completion and hover conversion.
- Definition selection and view-state restoration.
- Reference ordering.
- Rename version/hash checks, atomic application, and one-step undo.
- Retry preserves current editor and workspace state.

### Browser acceptance

- Live diagnostics update after editing without explicit validation.
- Completion and hover work across files and during a local syntax error.
- Definition and references navigate exact cross-file ranges.
- Rename updates every affected file, persists, reloads, and undoes as one
  operation.
- A concurrent edit rejects rename without partial changes.
- No automated accessibility violations.
- No off-origin source requests, CSP regressions, page overflow, or budget
  regressions.

## Documentation and roadmap

Batch A documents live diagnostics, completion, hover, protocol v2, and the
last-parseable behavior without marking Phase 3b complete. Batch B documents
navigation, references, rename, and the finished Phase 3b boundary.

After Batch B merges:

- mark Phase 3b shipped in `ROADMAP.md`;
- make visualization and analysis the active next slice;
- update `README.md`, `CHANGELOG.md`, and `docs/playground-design.md`;
- archive this specification and its implementation plan; and
- keep later visualization, analysis, WebLLM, offline, and extensibility phases
  active.

No ADR changes are required. Direct Monaco-to-compiler RPC and shared
compiler-owned semantics are already architectural decisions in
`docs/playground-design.md`; this specification defines the protocol v2 and
delivery details within that accepted boundary.

## Acceptance criteria

Phase 3b is complete when:

1. Desktop and browser language features use the same neutral Python semantic
   core.
2. The browser transport has no `pygls` or `lsprotocol` dependency.
3. Protocol v2 synchronizes exact revisioned workspace snapshots.
4. Live diagnostics cannot overwrite a newer revision.
5. Completion and hover work with current text and the last parseable semantic
   snapshot.
6. Definition and references return deterministic safe local locations.
7. Rename is Monaco-native, revision/hash checked, atomic, persistent, and
   undoable.
8. Browser and native conformance fixtures cover cross-file semantics.
9. Accessibility, CSP, privacy, layout, and performance gates pass.
10. Both delivery batches are documented and the completed spec/plan are
    archived only after Batch B merges.

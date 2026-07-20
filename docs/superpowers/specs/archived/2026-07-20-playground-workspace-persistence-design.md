# 2026-07-20 Playground Workspace and Persistence — Design

## Status

Shipped and archived on 2026-07-20.

This specification defines Phase 3a of the
[Modelable Playground Architecture](../../playground-design.md). It follows the
shipped browser compiler and single-file editor MVP, and establishes the
workspace foundation required by browser-native language services,
visualization, analysis, local AI, and offline support.

The repository [roadmap](../../../ROADMAP.md) makes the remaining Playground
program the immediate product priority and names this specification as the next
implementation slice.

## Context

The deployed Playground can edit one Modelable source file, validate and
format it, generate JSON Schema, import and export source, and recover from
compiler startup or operation failures. The existing browser compiler protocol
already accepts arrays of versioned sources for workspace validation and
compilation, but the React and Monaco application deliberately fixes the
source model to `file:///main.mdl`.

Later Playground phases require a durable virtual workspace rather than a
single mutable document:

- language services must resolve definitions and references across files;
- visualization and analysis must operate over the complete model graph;
- AI-generated changes must preview updates against an exact workspace
  snapshot; and
- offline support requires explicit, versioned local state.

Adding completion or visualization before this foundation would make those
features depend on temporary single-file state and force persistence and
conflict rules to be retrofitted later.

## Goals

- Replace the single-file application state with a browser-owned, multi-file
  Modelable workspace.
- Keep one Monaco model per open `.mdl` file and allow users to create, import,
  rename, delete, select, and edit files.
- Validate and compile the complete workspace through the existing compiler
  worker boundary.
- Persist source files, their versions, the active file, and minimal workspace
  metadata in versioned IndexedDB storage.
- Restore the last valid workspace automatically after reload.
- Prevent stale asynchronous compiler or persistence results from replacing
  newer source state.
- Provide explicit export and reset recovery when stored state is corrupt or
  incompatible.
- Preserve the static, local-only, same-origin deployment and the existing
  native/browser conformance and performance gates.

## Non-goals

This phase does not include:

- completion, hover, definition, references, rename, quick fixes, or an LSP
  transport;
- directory trees, arbitrary binary files, multiple simultaneous workspaces,
  or File System Access API synchronization;
- ZIP workspace import or export;
- visualization, lineage, compatibility, or governance views;
- WebLLM, remote model providers, model downloads, or AI-generated updates;
- service-worker installation or an offline runtime cache;
- persisting diagnostics, generated artifacts, diffs, compiler caches, or
  provider credentials; or
- changing Modelable parsing, validation, formatting, compilation, registry,
  or compatibility semantics.

Browser-native language services are Phase 3b. Visualization, analysis,
WebLLM, and offline delivery retain their existing later-phase order.

## Chosen approach

Introduce a small workspace domain layer in TypeScript, backed by a versioned
IndexedDB repository, and adapt the existing React, Monaco, and compiler-client
surfaces to consume immutable workspace snapshots.

This approach was selected over:

- adding multiple Monaco tabs while keeping persistence out of scope, which
  would create a second temporary state model and leave reload recovery
  undefined; and
- delivering one language-service vertical slice first, which would still
  depend on the single-file application state that this phase must replace.

The worker protocol remains compiler-owned. The browser workspace layer owns
file lifecycle and persistence but does not infer Modelable semantics.

## Architecture decision scope

No ADR change is required. The
[Playground Architecture](../../playground-design.md#8-virtual-workspace)
already assigns the virtual workspace to the browser application, IndexedDB to
automatic local persistence, Monaco to editing, and the Python worker to
compiler semantics. This specification narrows Phase 3 delivery and makes its
state, recovery, and testing contracts executable.

## Workspace model

The application uses immutable snapshots:

```ts
interface PlaygroundFile {
  path: string;
  content: string;
  version: number;
}

interface PlaygroundWorkspace {
  schemaVersion: 1;
  id: string;
  revision: number;
  files: PlaygroundFile[];
  activeFile: string;
}
```

The first implementation supports `.mdl` files only. Paths:

- use forward slashes;
- are relative to the virtual workspace root;
- reject empty segments, `.` and `..`, absolute paths, URL schemes, control
  characters, and NUL;
- end in `.mdl`; and
- are unique after separator normalization.

File and workspace versions are positive integers. Every accepted file
mutation increments that file's version and the workspace revision. Create,
rename, delete, import, and active-file changes produce a new snapshot through
pure workspace operations.

The workspace always contains at least one file. Deleting the last file is
rejected. A new or reset workspace contains `main.mdl` with the bundled example
and selects it as active.

## Application and Monaco integration

React owns:

- the current workspace snapshot;
- active operation and persistence state;
- restore or recovery state;
- normalized diagnostics for the current workspace revision; and
- generated artifacts tied to the revision that produced them.

Monaco owns one model per workspace file under a stable URI derived from its
normalized path, such as `file:///domains/customer.mdl`. Switching files
changes the editor model without recreating unaffected models. Rename replaces
the model URI while preserving content; delete disposes only the deleted
model. The editor adapter records and restores selection and view state in
memory during the current session, but Phase 3a does not persist cursor
positions.

The workspace UI provides:

- an accessible file list showing the active file;
- **New file**, **Import file**, **Rename**, and **Delete** actions;
- the existing source and generated-artifact editors; and
- a persistence status that distinguishes restoring, saved, saving, and
  recovery-required states.

All actions are keyboard reachable. File selection and destructive-action
confirmation do not rely on color alone.

## Compiler boundary

The existing `BrowserCompilerClient` remains the only application interface to
the compiler worker.

Validation and compilation send every workspace file as a sorted
`BrowserSource[]`. Formatting sends only the active file, then applies the
returned replacement to that file through the workspace domain layer.

The application captures the workspace revision for every request. Results
from an older revision may update timing telemetry but cannot replace current
diagnostics or generated artifacts.

Phase 3a may add or rename protocol methods only if the current request or
response cannot represent a complete workspace operation. Any protocol change
must retain explicit version rejection, structured-clone payloads, deterministic
source ordering, and native/browser conformance tests.

## IndexedDB persistence

Persistence uses one same-origin database named `modelable-playground` and a
versioned workspace store. The repository interface is independent of React:

```ts
interface WorkspaceRepository {
  load(id: string): Promise<PlaygroundWorkspace | undefined>;
  save(workspace: PlaygroundWorkspace): Promise<void>;
  remove(id: string): Promise<void>;
}
```

The initial release stores one well-known local workspace. The workspace
record contains only validated source state and the active file. Diagnostics,
artifacts, derived hashes, compiler runtime state, and secrets are never
stored.

Persistence rules:

- restoration completes before the initial workspace is opened in the
  compiler;
- edits schedule a short debounced save;
- structural file operations request an immediate save;
- each save carries the workspace revision, and the repository must not let an
  older completion overwrite a newer revision;
- successful saves update presentation state only when their revision still
  matches the current workspace; and
- `pagehide` may request a best-effort flush, but correctness cannot depend on
  asynchronous work completing during unload.

IndexedDB schema upgrades are explicit and transactional. An unknown
`schemaVersion` is incompatible rather than silently coerced.

## Restoration and recovery

Startup follows this sequence:

```text
open IndexedDB
  -> load and validate stored record
      -> open restored workspace in compiler
      -> or enter recovery-required state
```

A record is invalid when its envelope, versions, active file, normalized paths,
or file contents violate the workspace contract. Invalid or incompatible data
is not sent to the compiler and is not overwritten automatically.

Recovery-required state offers:

- **Export recovery data**, which downloads the stored record as JSON without
  interpreting its source as markup;
- **Reset local workspace**, which removes the stored record and creates the
  bundled default workspace; and
- **Retry**, for transient IndexedDB availability failures.

The editor remains usable with an in-memory default workspace when IndexedDB is
unavailable, but the UI must state that changes will not survive reload. A
later successful retry may persist the current in-memory workspace; it must not
replace it with older stored state.

## File operations and conflict rules

### Create

The user supplies a normalized relative `.mdl` path. Duplicate or unsafe paths
are rejected before a Monaco model, compiler request, or persistence write is
created.

### Import

Phase 3a imports one or more user-selected `.mdl` files into the current
workspace. Browser filenames become root-relative paths. Duplicate names
require an explicit replace confirmation; importing one file cannot replace
unrelated files.

### Rename

Rename is an atomic workspace mutation. The source file is unchanged, the old
path disappears, the new path becomes active, and current diagnostics and
artifacts become stale until revalidation.

### Delete

Delete requires confirmation, cannot remove the final file, disposes the
corresponding Monaco model, and invalidates derived results.

### Switching and editing

Switching changes only `activeFile`. Editing increments the active file version
and workspace revision, invalidates derived results from earlier revisions,
and schedules persistence. No file mutation performs an automatic compile.

## Error handling

- Compiler validation errors remain normal operation results and do not mark
  persistence unavailable.
- Worker failure retains the in-memory workspace and uses the existing runtime
  retry flow.
- IndexedDB open, load, save, or upgrade failures never clear the editor.
- A stale save or compiler result is ignored rather than merged.
- A failed create, import, rename, or delete leaves the prior workspace
  snapshot active.
- Export and reset errors are shown without exposing stored source in logs.

Application logs may include operation kind, workspace revision, file count,
duration, and error code. They must not include source contents, recovered
records, or imported file text.

## Security and privacy

- Workspace contents remain local and same-origin.
- IndexedDB stores no provider credentials or model responses.
- Imported filenames and persisted paths pass the same normalization and
  containment rules before becoming Monaco URIs.
- Recovery downloads are explicit user actions.
- Stored and imported source is rendered as text, never HTML.
- Existing CSP, worker isolation, Pyodide pinning, and no-CDN rules remain
  unchanged.

## Testing

### Workspace domain tests

- deterministic create, rename, delete, select, and edit transitions;
- path normalization and rejection;
- monotonic file and workspace versions;
- final-file deletion rejection; and
- stale derived-result invalidation.

### Persistence tests

- round-trip of a valid multi-file workspace;
- restoration of active file and versions;
- stale-save completion cannot overwrite a newer revision;
- corrupt and incompatible record recovery;
- reset and retry behavior; and
- unavailable IndexedDB leaves a clearly identified in-memory workspace.

### Application and Monaco tests

- stable model creation, switching, rename, deletion, and disposal;
- complete sorted workspace snapshots reach validation and compilation;
- formatting mutates only the active file;
- stale compiler responses are ignored; and
- accessible file actions and persistence states.

### Browser acceptance tests

- create or import a second file and compile a cross-file model;
- reload and restore exact source plus active-file selection;
- replace, rename, and delete behavior;
- corrupt-storage export and reset recovery;
- storage-unavailable fallback; and
- no regression in CSP, bounded layout, accessibility, conformance, or bundle
  budgets.

## Acceptance criteria

Phase 3a is complete when:

1. a user can create, import, rename, delete, select, and edit multiple `.mdl`
   files in one Playground workspace;
2. validation and compilation operate on the complete deterministic snapshot;
3. reload restores the exact last successfully persisted workspace and active
   file;
4. stale compiler and persistence completions cannot replace newer state;
5. corrupt, incompatible, or unavailable storage has an explicit, non-destructive
   recovery path;
6. no workspace source, generated artifact, diagnostic cache, or credential is
   transmitted or persisted outside the documented local boundary;
7. the shipped single-file workflows remain usable through the default
   `main.mdl` workspace; and
8. native/browser conformance, accessibility, security, performance, and size
   gates remain green.

## Roadmap effect

The remaining Playground program becomes Priority 1. Work proceeds in the
existing phase order:

1. Phase 3a workspace and persistence;
2. Phase 3b browser-native language services;
3. Phase 4 visualization;
4. Phase 5 analysis;
5. Phase 6 local AI and WebLLM; and
6. Phases 7–8 offline hardening and extensibility.

Only Phase 3a is approved by this specification. Each later phase still
requires its own accepted design and implementation plan. Scalable registration
remains the next non-Playground product track rather than being deleted.

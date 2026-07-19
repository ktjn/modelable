# 2026-07-19 Browser Editor MVP — Design

## Status

Approved for implementation planning on 2026-07-19.

This specification defines Phase 2 of the
[Modelable Playground Architecture](../../playground-design.md). It turns the
shipped browser compiler proof into a usable, deliberately single-file editor.
The broader playground document remains authoritative for later workspace,
visualization, local-AI, and offline phases.

The repository [roadmap](../../../ROADMAP.md) identifies this specification as
the next browser/WASM delivery slice.

## Context

The browser compiler proof established that Modelable can load a pinned,
same-origin Pyodide runtime, open in-memory source, validate and format it, and
generate JSON Schema through a versioned Web Worker protocol. It also
established native/browser conformance, performance budgets, and delivery under
`/modelable/playground/`.

The proof UI is intentionally minimal. It does not provide an editor-grade
source model, source-attached diagnostics, a structured application shell,
clear artifact lifecycle, or local file workflows. Building the multi-file
workspace or language-service phases on that temporary UI would mix product
work with infrastructure replacement.

## Goals

- Replace the proof UI with a small React application shell.
- Add one Monaco source model for one Modelable document.
- Preserve the existing `BrowserCompilerClient`, Pyodide worker, and compiler
  ownership boundary.
- Validate source and display ranged diagnostics as Monaco markers.
- Format source through the existing compiler operation while preserving editor
  undo.
- Generate and preview JSON Schema in a read-only Monaco model.
- Import one local Modelable or text file.
- Export the current Modelable source and generated JSON artifact.
- Keep the playground fully static, same-origin, and independent of network
  services.
- Establish browser, component, unit, accessibility, and bundle baselines for
  later playground phases.

## Non-goals

This phase does not include:

- multi-file workspaces, tabs, folders, or project manifests;
- IndexedDB, autosave, session restoration, or service-worker offline support;
- completion, hover, definition, references, rename, or the full LSP;
- graph, lineage, compatibility, or governance visualization;
- continuous or debounce-driven compilation;
- WebLLM, model downloads, conversational planning, or AI-generated updates;
- remote LLM providers or the VS Code Language Model API adapter;
- registry synchronization, publishing, or external-service operations;
- a new compiler protocol when the existing operations and payloads are
  sufficient.

These exclusions preserve the approved single-file boundary. In particular,
WebLLM remains an explicit
[Phase 6 local-AI capability](../../playground-design.md#phase-6-local-ai), not
an omitted feature. That phase will run WebLLM outside Pyodide through the
provider interface and feed untrusted model output through the existing typed
planning, validation, preview, and acceptance boundary.

## Chosen approach

Build an incremental React editor shell around the existing browser compiler
client.

This approach was selected over:

- adding Monaco to the existing imperative DOM UI, which would leave an
  unsuitable application foundation for later panels and workflows; and
- introducing the future virtual-workspace and persistence architecture now,
  which would violate the Phase 2 scope boundary.

Monaco is integrated directly through its official ESM APIs and Vite worker
imports. The implementation does not require a React-specific Monaco wrapper,
a third-party worker plugin, or CDN-hosted assets.

## Architecture decision scope

No ADR change is required. This specification implements the already accepted
static-playground architecture, same-origin deployment model, and
Pyodide/TypeScript worker boundary from `docs/playground-design.md`. React and
Monaco are already assigned to Phase 2 there. This design narrows delivery
scope and component responsibilities without introducing a new repository-wide
architecture, deployment model, data model, or security boundary.

## Architecture

```text
React application
├── source editor adapter ── Monaco source model
├── diagnostics and status UI
├── artifact preview ─────── read-only Monaco JSON model
└── import and export actions
            │
            ▼
BrowserCompilerClient
            │ existing versioned protocol
            ▼
Pyodide compiler worker
```

React owns layout and user-facing application state. Monaco owns editor text,
selection, editor commands, and undo history. The compiler worker remains the
authority for Modelable parsing, validation, formatting, and generation.

### Application shell

The browser entry point uses React's client `createRoot` API. The shell renders:

- a top toolbar;
- a primary source-editor pane;
- a generated-artifact pane;
- a status and diagnostics summary region; and
- recoverable initialization and operation-error states.

The shell stores only:

- runtime lifecycle state;
- the active operation, if any;
- the current source revision;
- normalized diagnostics and their summary;
- the latest generated artifact and its source revision; and
- import/export presentation state.

It does not mirror every source edit into React state.

### Monaco integration

The source editor uses one stable model URI such as `file:///main.mdl`.
The artifact preview uses a separate, read-only JSON model. Both models and
their editor instances are created and disposed by narrow React adapters.

Vite bundles only the Monaco workers required for the source editor and JSON
preview. `MonacoEnvironment.getWorker` returns locally bundled module workers;
no worker is loaded from a CDN.

Modelable diagnostics with valid source locations are converted into Monaco
markers under a dedicated owner. Document-level or malformed diagnostics remain
visible in the status region instead of being discarded.

Formatting calls the existing `source.format` operation and applies successful
output as one Monaco edit. This retains the editor's undo behavior instead of
replacing the model wholesale.

### Compiler boundary

The existing `BrowserCompilerClient` remains the sole application interface to
the Pyodide worker. Phase 2 uses the existing operations:

- runtime initialization;
- workspace/source opening, whose response contains validation results;
- source formatting; and
- JSON Schema compilation.

The implementation may normalize responses in a TypeScript adapter, but it
must not reimplement compiler semantics. A protocol change is allowed only when
an existing response cannot represent a required source range or artifact. Any
such change requires a focused protocol contract test and a design note in the
implementation plan.

## Runtime and operation lifecycle

The application uses these runtime states:

```text
loading → ready → working → ready
   │        │         │
   └──────► failed ◄──┘
```

`failed` covers runtime or worker failure and presents a clean retry path.
Ordinary validation or compilation errors are recoverable operation results and
do not make the runtime unavailable.

The source editor is usable while Pyodide initializes, but compiler actions are
disabled until the runtime is ready. Only one compiler operation runs at a
time, and duplicate action requests are suppressed.

Each operation captures the current source revision. A result for an older
revision may finish and update timing information, but it cannot overwrite the
diagnostics or artifact associated with newer source text. A worker crash
rejects pending requests, moves the runtime to `failed`, and permits a clean
worker restart without clearing the editor.

## User experience

The default wide layout places the editable Modelable source on the left and
the generated JSON Schema on the right. Narrow layouts stack the artifact pane
below the editor rather than compressing both panes.

The toolbar exposes:

- **Import**
- **Export source**
- **Validate**
- **Format**
- **Generate**
- **Export artifact**

Compiler actions show progress and are unavailable until initialization
completes. Keyboard operation includes normal Monaco behavior plus discoverable
shortcuts for validate, format, and generate.

### Validate

Validation sends the current source to the compiler and updates Monaco markers,
the diagnostic count, and document-level messages. It does not mutate source or
artifact state.

### Format

Formatting sends the current source to the compiler. Successful output is
applied as one editor operation. Diagnostics or operation failures leave the
source unchanged.

### Generate

Generation validates and compiles the current source, then pretty-prints the
successful JSON Schema result in the read-only artifact model. When a later
source revision or failed generation makes the displayed artifact outdated,
the artifact remains available but is visibly marked stale. It is not silently
presented as current output.

### Import and export

Import accepts one local `.mdl` or text file, reads it only as text, and replaces
the source model. When the current document differs from its last imported or
exported state, replacement requires confirmation. Imports have a documented
size limit and produce actionable errors for unsupported or unreadable files.

Source export downloads the current editor content with a sanitized `.mdl`
filename. Artifact export downloads the current generated result with a
sanitized `.json` filename. Export is implemented entirely in the browser.

## Security and privacy

- Source and generated artifacts remain in the browser.
- The application introduces no telemetry, remote APIs, dynamic CDN assets, or
  server persistence.
- Imported data is handled as text and is never executed.
- Exported filenames are sanitized.
- Monaco and Pyodide run in separate worker workloads.
- Content Security Policy compatibility is retained and any required exception
  must be isolated and documented.
- Generated artifacts and future model output are treated as untrusted data.

## Performance and observability

Compilation remains user-triggered in Phase 2. Continuous validation is deferred
until measurements show that it is affordable and useful.

The app records:

- runtime initialization duration;
- validation, formatting, and generation duration;
- React/application bundle size;
- Monaco editor and worker bundle sizes; and
- Pyodide/compiler asset size.

Existing compiler performance budgets remain in force. Phase 2 establishes
measured UI and Monaco baselines rather than inventing unvalidated size limits.

## Testing strategy

### Unit tests

Cover:

- runtime-state transitions;
- single-operation exclusion;
- stale-result rejection;
- diagnostic-to-marker conversion;
- artifact freshness;
- filename sanitization; and
- import/export helpers and size limits.

### Component tests

Cover:

- toolbar enablement during runtime and operations;
- runtime failure and retry;
- diagnostic summaries and document-level errors;
- stale-artifact labeling;
- import confirmation; and
- accessible labels and status announcements.

### Protocol and conformance tests

Retain the existing browser client, worker protocol, native/browser conformance,
and compiler performance tests. Add a protocol test only if the implementation
requires a narrowly justified payload change.

### Browser tests

Use the real locally served Pyodide compiler to verify:

1. the application loads under `/modelable/playground/`;
2. the compiler reaches ready state;
3. invalid source produces editor diagnostics;
4. valid source can be formatted;
5. JSON Schema can be generated and previewed;
6. source and artifact files can be exported;
7. a source file can be imported; and
8. compiler failure and retry preserve editor text.

The production build also receives a static-host smoke test confirming that
Monaco workers, Pyodide assets, the browser wheel, and dependency assets resolve
under the configured base path.

### Accessibility

Verify toolbar names, keyboard operation, focus order, visible focus, status
announcements, color contrast, and the stacked narrow-screen layout.

## Delivery sequence

Implementation planning should divide the work into independently reviewable
milestones:

1. React application shell and lifecycle state.
2. Monaco source and artifact editor integration.
3. Validation, diagnostics, formatting, and generation flows.
4. Import/export and artifact-freshness workflows.
5. Browser, accessibility, static-host, bundle, and documentation verification.

The final implementation PR updates the Phase 2 status in
`docs/playground-design.md`. After that PR merges, this specification and its
implementation plan move into their respective `archived/` directories.

## Acceptance criteria

Phase 2 is complete when:

- the production playground uses the React application shell;
- one Modelable document can be edited in Monaco;
- validation produces accurate Monaco markers and a textual summary;
- formatting preserves undo behavior;
- valid source generates a read-only JSON Schema preview;
- stale artifacts are never presented as current;
- one source file can be imported and source/artifact files can be exported;
- runtime failure is recoverable without losing source text;
- all assets remain same-origin and the workflow needs no backend service;
- the production build works under `/modelable/playground/`;
- required unit, component, protocol, browser, accessibility, and repository
  checks pass; and
- Phase 3 workspace/language-service work and Phase 6 WebLLM work remain
  explicitly deferred.

# Modelable Playground Architecture

> **Status:** Long-term product vision with Phase 1 shipped. The completed
> [Browser Compiler WASM Spike — Design](https://github.com/ktjn/modelable/blob/main/docs/superpowers/specs/archived/2026-07-18-browser-compiler-wasm-spike-design.md)
> is archived. Editor, visualization, persistence, local AI, offline, and
> plugin phases remain deferred.

## 1. Purpose

The Modelable Playground is a fully static, browser-native IDE for Modelable. It runs without backend services. Parsing, validation, compatibility analysis, code generation, visualization, and optional AI-assisted workflows execute on the user's device.

The playground is hosted as static assets, initially on GitHub Pages.

## 2. Goals

- No backend infrastructure.
- No server-side execution.
- No bundled credentials or secrets.
- Local-first and privacy-preserving execution.
- Offline operation after required assets have been cached.
- A production-quality editor for `.mdl` workspaces.
- Interactive visualization of domains, entities, projections, lineage, compatibility, and governance metadata.
- Shared compiler behavior between the CLI, language server, and browser.
- Deterministic validation and artifact generation independent of AI features.

## 3. Non-goals

The initial browser version does not provide:

- PostgreSQL-backed runtime services.
- Server-hosted collaboration.
- Remote workspace synchronization.
- Server-side registry or catalog synchronization.
- A browser-hosted LSP subprocess.
- Secure storage for provider API keys.
- Arbitrary access to the user's local filesystem without explicit browser permission.

## 4. Constraints

- The application must deploy as static files.
- Python code executes through CPython compiled to WebAssembly.
- Browser APIs are asynchronous and must not block the main UI thread.
- Large language models may require multi-gigabyte downloads and WebGPU support.
- GitHub Pages serves the application under a repository-relative base path.
- Browser storage quotas vary by browser and device.
- Browser support for the File System Access API is not uniform.

## 5. High-level architecture

```text
Static hosting
└── React application
    ├── Application shell
    ├── Workspace explorer
    ├── Monaco editor
    ├── Diagnostics and reports
    ├── Artifact preview
    ├── Visualization canvas
    ├── Persistence adapters
    ├── Compiler RPC client
    └── LLM provider client

Compiler worker
└── Pyodide
    └── modelable-core
        ├── Parser
        ├── Resolver
        ├── Validator
        ├── Formatter
        ├── Compatibility engine
        ├── Lineage engine
        ├── Governance analysis
        ├── Artifact generators
        └── Visualization projections

LLM worker
└── Browser provider
    ├── WebLLM over WebGPU
    ├── Optional local Ollama
    └── Optional user-supplied remote provider
```

The React UI owns presentation, interaction, browser storage, graph layout, and browser integration. `modelable-core` owns language semantics and emits normalized, serializable result objects.

## 6. Repository structure

Target structure:

```text
packages/
  modelable-core/
  modelable-cli/
  modelable-lsp/
  modelable-web/

web/
  src/
    app/
    editor/
    visualization/
    workers/
    workspace/
    llm/
    storage/
  public/
    pyodide/
    wheels/
```

### 6.1 modelable-core

Pure Python compiler functionality.

Requirements:

- No `click` dependency.
- No terminal rendering.
- No sockets.
- No subprocesses.
- No mandatory PostgreSQL dependency.
- No assumptions about process working directories.
- Public APIs accept strings, immutable data, or virtual workspace abstractions.
- Public APIs return serializable data structures.

### 6.2 modelable-cli

Owns:

- Click command definitions.
- Terminal output.
- Local filesystem handling.
- Environment-variable configuration.
- CLI-specific audit and provenance output.

### 6.3 modelable-lsp

Owns:

- JSON-RPC transport.
- `pygls` integration.
- Desktop editor integration.

Language semantics must remain in `modelable-core` so browser and LSP behavior do not diverge.

### 6.4 modelable-web

Owns browser-specific adapters:

- Pyodide entry points.
- Worker-facing RPC methods.
- Conversion to JSON-compatible DTOs.
- JavaScript callback integration for asynchronous LLM providers.
- Browser-specific virtual filesystem adapters.

## 7. Browser runtime

## 7.1 Compiler worker

The compiler runs in a dedicated module Web Worker containing Pyodide and the browser-compatible Modelable wheel.

Responsibilities:

- Initialize Pyodide.
- Load required Python packages.
- Install the bundled Modelable wheel.
- Maintain compiler workspace state.
- Execute compiler requests.
- Return structured responses.
- Isolate Python failures from the main UI thread.

The worker must never directly manipulate DOM state.

## 7.2 Worker lifecycle

Worker states:

```text
uninitialized -> loading-runtime -> loading-packages -> ready -> failed
```

The UI must expose initialization progress and retain an actionable error state. Requests received before readiness are queued or rejected with a typed initialization error.

The worker should remain long-lived to preserve parsed workspace state and avoid repeated Pyodide startup costs.

## 7.3 RPC protocol

Use a versioned request-response protocol.

```ts
interface RpcRequest<T> {
  protocolVersion: 1;
  id: string;
  method: string;
  payload: T;
}

interface RpcSuccess<T> {
  protocolVersion: 1;
  id: string;
  ok: true;
  result: T;
}

interface RpcFailure {
  protocolVersion: 1;
  id: string;
  ok: false;
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}
```

Initial compiler methods:

- `workspace.open`
- `workspace.updateFile`
- `workspace.removeFile`
- `workspace.snapshot`
- `validate`
- `format`
- `complete`
- `hover`
- `definition`
- `references`
- `rename`
- `compile`
- `diff`
- `lineage`
- `governance`
- `graph`
- `llm.prepareRequest`
- `llm.applyResponse`

Use structured clone-compatible payloads. Avoid returning live Python proxy objects.

## 8. Virtual workspace

The browser application must support multi-file Modelable workspaces.

```ts
interface WorkspaceFile {
  path: string;
  content: string;
  version: number;
  language: "mdl" | "json" | "yaml" | "sql" | "protobuf" | "text";
}

interface WorkspaceSnapshot {
  id: string;
  files: WorkspaceFile[];
  activeFile?: string;
}
```

The compiler worker maintains a normalized workspace snapshot. UI updates are transmitted as versioned file mutations.

### 8.1 Persistence

Persistence layers:

1. In-memory state for the active session.
2. IndexedDB for automatic local persistence.
3. File System Access API where supported and explicitly authorized.
4. Import/export as individual files or ZIP archives.
5. Shareable URL payloads for small single-file examples.

Do not automatically upload workspace content.

### 8.2 Conflict handling

When a file-backed workspace changes externally, the UI must present a three-way choice:

- Reload external version.
- Keep browser version.
- Open a diff editor.

Silent overwrites are prohibited.

## 9. Editor architecture

## 9.1 Monaco editor

Monaco is the primary `.mdl` editor.

Required capabilities:

- Syntax highlighting.
- Bracket matching.
- Folding.
- Diagnostics.
- Completion.
- Hover information.
- Go-to-definition.
- Find references.
- Rename.
- Document formatting.
- Quick fixes.
- Symbol navigation.
- Multi-file models.
- Read-only generated artifact editors.
- Side-by-side compatibility diff editor.

## 9.2 Browser-native language services

The initial browser version must not run the full LSP server. Implement Monaco providers that call compiler RPC methods directly.

```text
Monaco provider
    -> compiler RPC client
        -> compiler worker
            -> modelable-core language service
```

This avoids JSON-RPC-over-JSON-RPC, process assumptions, and `pygls` browser compatibility issues.

The semantic implementation should be shared with the desktop language server wherever possible.

## 9.3 Diagnostics

Validation is triggered:

- After a configurable debounce following edits.
- On explicit save.
- Before compilation.
- Before AI-generated changes are applied.

Diagnostics must include stable codes and exact source ranges.

```ts
interface SourceRange {
  file: string;
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

interface Diagnostic {
  code: string;
  severity: "error" | "warning" | "information" | "hint";
  message: string;
  range: SourceRange;
  related?: Array<{
    message: string;
    range: SourceRange;
  }>;
}
```

## 9.4 Editor state

Persist locally:

- Open files.
- Active file.
- Cursor positions.
- Editor layout.
- Selected artifact target.
- Selected visualization mode.

Do not persist provider secrets.

## 10. Visualization architecture

Visualization is a first-class compiler projection. The Python compiler emits semantic graph data. The browser owns layout and rendering.

Do not infer Modelable semantics independently in TypeScript.

## 10.1 Visualization modes

### Domain graph

Shows:

- Domains.
- Domain ownership.
- Entities.
- Cross-domain dependencies.
- Published versions.

### Entity diagram

Shows:

- Fields.
- Types.
- Keys.
- Optionality.
- Annotations.
- Classification metadata.
- Relationships.
- Version evolution.

### Projection graph

Shows:

- Canonical models.
- Projections.
- Projection types.
- Generated artifacts.
- Dependencies between projections.

### Field lineage graph

Shows field-level derivation:

```text
canonical field -> projected field -> generated artifact field
```

Edges may contain transformation, rename, filtering, and source metadata.

### Compatibility view

Shows changes between versions:

- Additions.
- Removals.
- Type changes.
- Cardinality changes.
- Annotation changes.
- Breaking changes.
- Affected projections and artifacts.

### Governance view

Shows:

- Missing ownership.
- Missing classification.
- Missing access metadata.
- PII distribution.
- Unresolved lineage.
- Policy violations.

## 10.2 Graph DTO

```ts
type GraphNodeKind =
  | "workspace"
  | "domain"
  | "entity"
  | "version"
  | "field"
  | "projection"
  | "artifact"
  | "external-source"
  | "governance-gap";

type GraphEdgeKind =
  | "contains"
  | "references"
  | "depends-on"
  | "projects"
  | "derived-from"
  | "generates"
  | "supersedes"
  | "violates";

interface ModelGraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  range?: SourceRange;
  metadata: Record<string, unknown>;
}

interface ModelGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: GraphEdgeKind;
  label?: string;
  metadata: Record<string, unknown>;
}

interface ModelGraph {
  schemaVersion: 1;
  nodes: ModelGraphNode[];
  edges: ModelGraphEdge[];
  diagnostics: Diagnostic[];
}
```

Node and edge identifiers must be deterministic for the same semantic model. This allows stable selection, layout reuse, and incremental graph updates.

## 10.3 Rendering

Use React Flow for interaction and rendering.

The rendering layer owns:

- Node components.
- Edge components.
- Selection.
- Pan and zoom.
- Minimap.
- Filtering.
- Collapsing and expansion.
- Context menus.
- Export.

Use ELK.js as the preferred layout engine. Dagre may be used for simpler trees. Layout must execute in a separate worker for large graphs.

Python must not emit screen coordinates.

## 10.4 Editor and graph synchronization

Synchronization is bidirectional:

```text
Editor cursor -> highlight semantic graph node
Graph selection -> reveal source range
Diagnostic selection -> reveal editor range and graph context
Version selection -> update compatibility diagram
Artifact selection -> trace back to canonical source
```

Selection state uses semantic node identifiers, not labels or current coordinates.

## 10.5 Large graph behavior

For large workspaces:

- Collapse fields by default.
- Render domain and entity summaries first.
- Load field-level lineage on demand.
- Virtualize lists and side panels.
- Batch graph updates.
- Cache layouts by graph hash.
- Limit animated transitions.
- Move layout calculations off the main thread.

## 10.6 Export

Support:

- SVG export.
- PNG export.
- JSON graph export.
- Copy selected subgraph as Mermaid where representable.

Exported images must include a generated timestamp and Modelable version only when explicitly enabled. Workspace source content must not be embedded unintentionally.

## 11. Main application layout

Desktop layout:

```text
┌────────────────┬────────────────────────────┬───────────────────────┐
│ Workspace      │ Editor                     │ Visualization         │
│ explorer       │                            │                       │
│                │ Monaco                     │ Domain/entity/lineage │
│ files/models   │                            │ graph                 │
├────────────────┴────────────────────────────┴───────────────────────┤
│ Diagnostics | Generated artifacts | Compatibility | Governance      │
└─────────────────────────────────────────────────────────────────────┘
```

Panels must be resizable and individually collapsible.

On narrow screens, use tabbed views rather than shrinking all three primary panels simultaneously.

## 12. LLM architecture

AI assistance is optional. Core compiler behavior must not depend on model availability.

## 12.1 Default provider

The default playground provider is WebLLM running in a dedicated Web Worker using WebGPU.

Responsibilities:

- Download model assets after explicit user action.
- Report download and initialization progress.
- Execute prompts locally.
- Stream tokens to the UI where useful.
- Return normalized responses to the compiler workflow.

## 12.2 Provider abstraction

```ts
interface LlmRequest {
  system: string;
  user: string;
  temperature: number;
  responseFormat: "text" | "json";
  schema?: Record<string, unknown>;
}

interface LlmResponse {
  content: string;
  provider: string;
  model: string;
  promptTokens?: number;
  completionTokens?: number;
}

interface LlmProvider {
  readonly id: string;
  readonly model: string;
  initialize(onProgress?: (progress: number, message: string) => void): Promise<void>;
  complete(request: LlmRequest): Promise<LlmResponse>;
  dispose(): Promise<void>;
}
```

Potential providers:

- `WebGpuProvider` using WebLLM.
- `OllamaProvider` calling a user-controlled local Ollama endpoint.
- `RemoteByokProvider` using a user-supplied key where browser CORS policies permit.
- `HeuristicProvider` for deterministic non-LLM behavior.

## 12.3 Python integration

Browser inference is asynchronous. The existing synchronous Python provider boundary must not be used directly.

Preferred workflow:

1. Python constructs a normalized LLM request.
2. Compiler worker returns the request to TypeScript.
3. TypeScript invokes the selected provider.
4. TypeScript returns the response to the compiler worker.
5. Python validates and applies the generated content.
6. The UI shows a diff before modifying the workspace.

AI-generated changes must never bypass parser and validator checks.

## 12.4 AI interaction design

Initial AI actions:

- Generate an entity from a natural-language description.
- Explain a model or diagnostic.
- Suggest a projection.
- Apply a natural-language model update.
- Import a supported external schema.
- Recommend governance metadata.

Every mutating action must:

- Produce a preview.
- Show a textual or structural diff.
- Validate the proposed result.
- Require explicit user acceptance.
- Record provider and model metadata in local provenance data.

## 13. Artifact generation

Generated artifacts are returned as an in-memory collection:

```ts
interface GeneratedFile {
  path: string;
  mediaType: string;
  content: string | Uint8Array;
  sourceRefs: string[];
}
```

The UI supports:

- Syntax-highlighted preview.
- Search.
- Copy.
- Individual download.
- Download all as ZIP.
- Trace generated sections back to source model elements.

Generators should load lazily to reduce initial startup and memory usage.

## 14. Incremental compiler behavior

The browser runtime should avoid recompiling the entire workspace after every keystroke.

Target architecture:

- File content hashes.
- Parsed syntax tree cache.
- Dependency graph.
- Resolved symbol cache.
- Invalidated semantic subgraphs.
- Cached visualization projections.
- Cached generated artifacts by target and workspace hash.

Initial implementation may revalidate the workspace, but APIs and DTOs should not prevent incremental behavior later.

## 15. Offline and caching

Use a service worker to cache application assets.

Cache groups:

- Application shell.
- Pyodide runtime.
- Python wheels.
- WebLLM runtime.
- User-selected model assets.
- Documentation and examples.

Model assets must only download after user confirmation. Display expected download size where available.

IndexedDB stores:

- Workspace snapshots.
- Editor state.
- Cached compiler metadata.
- Graph layouts.
- Model download state.

A service worker update must not silently invalidate unsaved workspace state.

## 16. Security model

## 16.1 Principles

- No bundled secrets.
- No implicit network access.
- Local execution by default.
- Explicit user consent before model downloads or remote calls.
- Validate all data crossing worker boundaries.
- Treat imported workspace files as untrusted input.

## 16.2 Content Security Policy

Use a restrictive CSP. Avoid `unsafe-eval` unless a required runtime makes it unavoidable. If Pyodide or WebLLM requires exceptions, document and isolate them.

Restrict connections to:

- The static site origin.
- Explicitly configured model asset origins.
- User-selected local or remote LLM endpoints.

## 16.3 API keys

Do not ship application-owned cloud API keys.

User-supplied keys:

- Remain in memory by default.
- Are never placed in URLs.
- Are never included in logs, diagnostics, provenance, or exported workspaces.
- Are cleared when the tab closes or the provider is disconnected.

IndexedDB and `localStorage` are not secure secret stores.

## 16.4 Generated content

Treat LLM output as untrusted data.

- Parse and validate before use.
- Never evaluate generated JavaScript or Python.
- Escape generated text before rendering as HTML.
- Require review before applying edits.

## 17. Performance targets

Initial targets on a modern desktop browser:

- Application shell interactive within 2 seconds excluding uncached Pyodide download.
- Compiler ready within 5 seconds after cached startup.
- Validation response below 250 ms for small workspaces.
- Editor remains responsive during compilation and inference.
- Graph interactions remain above 30 FPS for 1,000 visible nodes.
- No main-thread task above 100 ms during normal editing.

Track:

- Runtime download size.
- Wheel size.
- Initialization duration.
- Validation duration.
- Compilation duration by target.
- Graph projection and layout duration.
- LLM model download and token generation rates.
- Peak browser memory.

## 18. Browser compatibility

Primary target:

- Current Chromium-based desktop browsers with WebAssembly and WebGPU.

Secondary target:

- Firefox and Safari for compiler/editor features where Pyodide works.

WebLLM functionality must be feature-detected. When WebGPU is unavailable, the compiler and visual editor remain fully usable.

The File System Access API must have import/export fallbacks.

## 19. Accessibility

- All editor-adjacent controls must be keyboard accessible.
- Graph nodes must expose textual labels and roles.
- Provide a navigable tree/table alternative to the graph.
- Do not communicate compatibility or governance status by color alone.
- Support reduced motion.
- Preserve usable contrast in light and dark themes.
- Exported diagrams should include accessible textual metadata where practical.

## 20. Testing strategy

## 20.1 Core conformance

Run the same language fixtures against:

- CLI execution.
- LSP services.
- Browser/Pyodide APIs.

Expected diagnostics, generated artifacts, and graph DTOs must match.

## 20.2 Unit tests

Cover:

- RPC serialization.
- Workspace mutation handling.
- Monaco provider adapters.
- Graph DTO conversion.
- Graph filtering and selection.
- Provider abstraction.
- Persistence adapters.

## 20.3 Integration tests

Use Playwright to verify:

- Pyodide initialization.
- Editing and diagnostics.
- Multi-file navigation.
- Compilation and downloads.
- Graph rendering and editor synchronization.
- Compatibility diff workflow.
- Offline startup after caching.
- WebLLM feature detection and mocked provider flows.

## 20.4 Visual regression tests

Capture stable scenarios for:

- Domain graph.
- Entity diagram.
- Lineage graph.
- Compatibility view.
- Governance view.
- Main responsive layouts.

Graph correctness must also be asserted structurally. Screenshot tests alone are insufficient.

## 21. Build and deployment

GitHub Actions performs:

1. Python linting and tests.
2. Browser-compatible wheel build.
3. TypeScript checks and tests.
4. React production build.
5. Playwright integration tests.
6. Static asset size checks.
7. GitHub Pages artifact upload.
8. GitHub Pages deployment.

Published assets:

- React application.
- Pyodide runtime or pinned external runtime references.
- Browser-compatible Modelable wheel.
- Required Python wheels.
- WebLLM runtime.
- Static documentation and examples.

Large LLM models should normally remain separately cached provider assets rather than repository artifacts.

## 22. Plugin architecture

A later plugin API may support:

- Artifact viewers.
- Visualization projections.
- Generator targets.
- Importers.
- Deterministic transformations.
- LLM providers.

Plugins must declare capabilities and operate through typed interfaces. Arbitrary unsigned code execution is not supported in the static playground.

## 23. Observability

The default deployment should not send workspace content or prompts to telemetry systems.

Permitted local diagnostics:

- Runtime timings.
- Worker failures.
- Memory estimates.
- Cache status.

Any remote telemetry must be opt-in, documented, and scrubbed of source text, prompts, generated artifacts, file names, and identifiers.

## 24. Delivery roadmap

### Phase 1: browser compiler spike — shipped

The static proof is deployed under
[`/modelable/playground/`](https://ktjn.github.io/modelable/playground/). It
supports Validate, Format, and Generate JSON Schema through
`BrowserCompilerClient` protocol v1 and a module Web Worker. The worker loads
Pyodide `314.0.2` with Python `3.14.2`; the runtime, locked Python dependencies,
fixtures, and generated `modelable-browser` wheel are all same-origin assets.

The final Windows/Chromium gate measured these gzip-compressed payloads:

- `modelable-browser` wheel: 57,224 bytes (2 MiB budget).
- Application HTML, CSS, and JavaScript: 13,721 bytes (750 KiB budget).
- Additional Python wheels: 2,528,120 bytes (15 MiB budget), excluding the
  base Pyodide runtime.

The same gate measured these browser medians:

- Cold initialization: 2,371.54 ms (20,000 ms budget).
- Cached initialization: 2,861.93 ms (5,000 ms budget).
- Validation: 11.50 ms (500 ms budget).
- JSON Schema generation: 32.30 ms (1,000 ms budget).

These figures are one final local measurement, not service-level guarantees;
CI reruns the budgets to catch regressions. The proof intentionally defers the
editor, visualization, persistence, and AI phases below. The completed scope
and acceptance criteria are archived in
[Browser Compiler WASM Spike — Design](https://github.com/ktjn/modelable/blob/main/docs/superpowers/specs/archived/2026-07-18-browser-compiler-wasm-spike-design.md).

### Phase 2: editor MVP

**Status: Shipped.**

The shipped single-file editor includes:

- a responsive React application shell;
- Monaco source editing with ranged diagnostics and undo-preserving formatting;
- selected generated-artifact preview in a read-only Monaco model;
- explicit source import plus source and artifact export;
- recoverable compiler failure with retry while preserving source text;
- unit, component, keyboard, and automated accessibility coverage; and
- static, same-origin deployment under `/modelable/playground/`.

The completed scope and acceptance criteria are archived in
[Browser Editor MVP — Design](superpowers/specs/archived/2026-07-19-browser-editor-mvp-design.md).

### Phase 3: workspace and language services

- Multi-file workspace.
- Completion and hover.
- Definition, references, and rename.
- IndexedDB persistence.

### Phase 4: visualization MVP

- Stable graph DTO.
- Domain graph.
- Entity diagram.
- Source navigation from graph nodes.
- ELK layout worker.

### Phase 5: analysis views

- Field lineage.
- Compatibility visualization.
- Governance visualization.
- SVG and PNG export.

### Phase 6: local AI

- WebLLM provider.
- Model download UX.
- Generate and explain actions.
- Validated update preview and acceptance flow.

### Phase 7: offline and hardening

- Service worker.
- Offline workspace support.
- Performance optimization.
- Accessibility review.
- Security review.
- Cross-browser validation.

### Phase 8: extensibility

- Plugin contracts.
- Additional visualization modes.
- Optional local Ollama provider.
- Optional GitHub integration using explicit user authorization.

## 25. Architectural decisions

1. The playground remains fully static.
2. Python compiler execution runs in Pyodide inside a Web Worker.
3. LLM inference runs outside Pyodide through an asynchronous TypeScript provider interface.
4. Modelable semantics remain in `modelable-core`.
5. Monaco integrates directly with browser compiler APIs rather than hosting the full LSP server.
6. Visualization is generated from compiler-owned semantic graph DTOs.
7. React owns rendering and ELK/Dagre owns graph layout.
8. AI is optional and never required for validation or generation from deterministic targets.
9. All AI-generated mutations require validation, diff preview, and explicit acceptance.
10. No secrets are embedded in the static application.

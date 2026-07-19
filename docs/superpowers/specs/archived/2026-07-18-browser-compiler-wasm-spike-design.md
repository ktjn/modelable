# 2026-07-18 Browser Compiler WASM Spike — Design

## Status

Shipped and archived on 2026-07-18.

This specification defines the Phase 0 browser-compiler proof of concept. It
replaces the first delivery phase in
[Modelable Playground Architecture](../../../playground-design.md) as the
authoritative scope for the next browser/WASM slice. The broader playground
document remains the long-term product vision.

## Problem

Modelable currently ships one Python distribution containing compiler, CLI,
language-server, registry, database, and terminal dependencies. The compiler
has useful in-memory entry points, but the published wheel cannot be installed
unchanged in Pyodide because its mandatory dependency set includes desktop and
native components such as `pygls` and `psycopg[binary]`.

The playground architecture assumes that a browser-compatible wheel, worker
protocol, in-memory artifact surface, and GitHub Pages deployment already have
clear implementation paths. Those assumptions have not been proven. Building
Monaco, visualization, persistence, or local AI before proving the compiler
runtime would multiply risk across unrelated subsystems.

## Goals

- Prove that the existing Modelable compiler source can execute in Pyodide
  without splitting the repository into multiple maintained Python source
  trees.
- Produce a deterministic browser-only wheel and dependency lock that exclude
  CLI, LSP, PostgreSQL, sockets, subprocesses, and terminal rendering.
- Open one or more in-memory `.mdl` sources and return serializable validation
  results.
- Format an in-memory `.mdl` source without reading or writing host files.
- Generate JSON Schema into in-memory artifacts without filesystem output.
- Expose those operations through a versioned Web Worker request-response
  protocol.
- Run the same conformance fixtures through native Python and browser/Pyodide
  and compare normalized results exactly.
- Measure and enforce initial asset-size, startup, validation, and compilation
  budgets.
- Publish a static proof of concept under the existing GitHub Pages site at
  `/modelable/playground/`.

## Non-goals

This spike does not include:

- Monaco or another production editor.
- A React application shell.
- Graph, lineage, compatibility, or governance visualization.
- IndexedDB, File System Access API, ZIP import/export, or service-worker
  offline support.
- WebLLM, Ollama, remote providers, conversational planning, or AI-generated
  changes.
- The full LSP server or JSON-RPC.
- Registry synchronization, publishing, PostgreSQL access, or external-service
  operations.
- A plugin system.
- A repository-wide split into `modelable-core`, `modelable-cli`,
  `modelable-lsp`, and `modelable-web` packages.
- Changing the supported behavior of the existing `modelable` wheel or CLI.

## Approach

### Browser distribution

Create a second distribution named `modelable-browser`. Its import package
remains `modelable`, but its wheel is assembled from the existing
`cli/src/modelable` source by a deterministic staging script. The repository
does not contain a copied browser fork of compiler source.

The staging script must:

1. copy the browser-compatible module closure into a temporary build root;
2. generate browser-specific package metadata;
3. reject imports of forbidden desktop/runtime dependencies;
4. build a pure-Python wheel;
5. emit a machine-readable manifest containing the Modelable commit, wheel
   hash, Pyodide version, Python version, and locked browser dependencies; and
6. remove the temporary build root after success or failure.

The browser distribution must not declare `click`, `rich`, `pygls`,
`psycopg`, or `psycopg-binary`. Browser code must not import `modelable.cli`,
`modelable.commands`, `modelable.lsp`, database-backed registry adapters, or
terminal renderers.

### Runtime and dependency lock

Pin the spike to:

- Pyodide `314.0.2`;
- CPython `3.14.2`;
- the `pyemscripten_2026_0_wasm32` platform; and
- exact browser dependency versions in a committed lock/manifest.

The browser lock may use Pyodide-provided versions that differ from the desktop
wheel only when the difference is explicit in the manifest and the full
conformance suite passes. In particular, the spike may use Pyodide's compatible
Pydantic and `pydantic-core` pair instead of attempting to load a native
desktop wheel.

Pyodide and all required Python packages must load from same-origin static
assets in the deployed proof of concept. The browser test must fail when it
requires an undeclared network origin.

### In-memory compiler facade

Add a browser-neutral Python application facade over existing compiler
primitives. The facade accepts immutable source DTOs and returns JSON-compatible
DTOs. It does not depend on JavaScript, Pyodide, browser globals, the CLI, or
the LSP.

The initial interface is:

```python
@dataclass(frozen=True)
class BrowserSource:
    uri: str
    text: str
    version: int


@dataclass(frozen=True)
class BrowserArtifact:
    path: str
    media_type: str
    content: str
    source_refs: tuple[str, ...]


class BrowserCompiler:
    def open_workspace(self, sources: tuple[BrowserSource, ...]) -> BrowserWorkspaceResult: ...
    def format_source(self, source: BrowserSource) -> BrowserFormatResult: ...
    def compile_json_schema(
        self,
        sources: tuple[BrowserSource, ...],
    ) -> BrowserCompileResult: ...
```

`open_workspace` delegates to `load_workspace_from_sources()` and preserves
source URIs, content hashes, stable diagnostic codes, severities, messages, and
ranges. Requests with duplicate URIs or non-positive versions fail with typed
input errors.

`format_source` parses and renders exactly one source. Invalid input returns
diagnostics and no replacement text.

`compile_json_schema` validates the complete in-memory workspace first. Any
error-severity diagnostic prevents generation. Successful generation returns
sorted `BrowserArtifact` values and does not create files.

### In-memory artifact boundary

Introduce a narrow artifact-producing function for JSON Schema. The existing
CLI emitter remains a filesystem adapter around this compiler-owned result.
Browser code consumes the in-memory artifacts directly.

The compiler-owned operation must be deterministic:

- artifacts sort by normalized relative path;
- text uses UTF-8 and `\n` line endings;
- media type is `application/schema+json`;
- source references use canonical Modelable refs; and
- the same workspace produces byte-identical content in native Python and
  Pyodide.

This spike does not generalize every emitter. The interface must allow later
targets to return the same artifact DTO without requiring a new browser
protocol.

## Worker protocol

Run Pyodide and `BrowserCompiler` inside one dedicated module Web Worker. The
main thread communicates through a small TypeScript client.

Every request and response includes `protocolVersion: 1` and a caller-generated
string ID:

```ts
type BrowserCompilerMethod =
  | 'runtime.initialize'
  | 'workspace.open'
  | 'source.format'
  | 'compile.jsonSchema';

interface BrowserCompilerRequest {
  protocolVersion: 1;
  id: string;
  method: BrowserCompilerMethod;
  payload: unknown;
}

interface BrowserCompilerSuccess<T> {
  protocolVersion: 1;
  id: string;
  ok: true;
  result: T;
}

interface BrowserCompilerFailure {
  protocolVersion: 1;
  id: string;
  ok: false;
  error: {
    code:
      | 'INITIALIZATION_FAILED'
      | 'INVALID_REQUEST'
      | 'UNSUPPORTED_PROTOCOL'
      | 'COMPILER_FAILED';
    message: string;
  };
}
```

Payloads must be structured-clone compatible. Python proxy objects never cross
the worker boundary. Unknown methods, protocol versions other than `1`,
malformed source DTOs, and requests before successful initialization return
typed failures without terminating the worker.

The worker state machine is:

```text
uninitialized -> initializing -> ready
                         \-> failed
```

Initialization is idempotent. Concurrent callers share one initialization
promise. A failed worker remains failed and reports the same sanitized error
until it is replaced.

## Static proof of concept

The spike UI is intentionally minimal HTML and TypeScript, not the future React
playground. It provides:

- runtime initialization status;
- one editable `.mdl` text area preloaded from a conformance fixture;
- Validate, Format, and Generate JSON Schema actions;
- a diagnostics panel;
- an artifact preview; and
- a metrics panel.

The proof of concept exists to exercise the real worker and compiler facade. It
is not a reusable visual design commitment.

## Conformance

Use committed fixtures covering:

- one valid single-file workspace;
- one valid multi-file, cross-domain workspace;
- syntax diagnostics;
- semantic diagnostics;
- reference diagnostics;
- formatting; and
- JSON Schema generation.

A native-Python harness and a Playwright browser harness both normalize results
to committed JSON snapshots. The browser result must match native Python for:

- diagnostic code, severity, message, URI, and range;
- formatted source;
- artifact path, media type, content, and source refs; and
- deterministic ordering.

Platform-specific stack traces, timing values, and absolute filesystem paths
must not enter snapshots.

## Performance and size budgets

Measure production assets and three Chromium runs on the GitHub-hosted Ubuntu
runner. Timing gates use the median of three runs.

Initial hard budgets are:

- `modelable-browser` wheel: at most 2 MiB compressed;
- application JavaScript, worker JavaScript, CSS, and HTML combined: at most
  750 KiB compressed, excluding Pyodide and Python wheels;
- all additional Python wheels required by Modelable: at most 15 MiB
  compressed, excluding the base Pyodide runtime;
- cold `runtime.initialize`: at most 20 seconds;
- cached `runtime.initialize`: at most 5 seconds;
- validation of the small conformance workspace: at most 500 ms; and
- JSON Schema compilation of the small conformance workspace: at most
  1 second.

The build fails when a size budget is exceeded. Browser integration fails when
a timing budget is exceeded. Each failure prints the measured value and budget.

## Pages integration

The existing documentation workflow remains the sole owner of the
`github-pages` environment and deployment.

The workflow must:

1. build strict MkDocs output into `site/`;
2. build the WASM proof of concept;
3. copy the proof into `site/playground/`;
4. verify that `site/playground/index.html` references repository-relative
   assets;
5. upload one combined Pages artifact; and
6. deploy once.

The proof must work at `/modelable/playground/`; it must not assume origin-root
hosting. Pull requests build and test the proof but do not deploy it.

## Security and privacy

- The spike performs no LLM inference and accepts no provider credentials.
- Workspace source remains in the browser and is not sent to telemetry.
- Production assets use a restrictive content security policy.
- Runtime and wheel assets load only from the static site origin.
- Worker errors returned to the UI omit Python stack traces, local build paths,
  environment variables, and source text.
- Imported source is treated as untrusted text and is never evaluated as Python
  or JavaScript.

## ADR impact

No separate ADR changes in this spike. The specification narrows and validates
the existing browser architecture rather than establishing a new
repository-wide package structure or shipped public protocol. If the spike
succeeds, the follow-up editor decision must promote the proven browser
distribution, worker protocol, and Pages ownership boundaries into the
appropriate durable architecture documentation before implementation expands
beyond the proof of concept.

## Verification

The implementation must add one documented command that performs the complete
spike gate locally. CI runs the same underlying steps:

1. browser wheel build and forbidden-import scan;
2. native compiler facade tests;
3. existing CLI quality gates;
4. TypeScript type checking and unit tests;
5. production static build and size checks;
6. Playwright conformance and interaction tests;
7. timing-budget checks; and
8. strict MkDocs build with the combined Pages artifact.

The existing `AGENTS.md` commands remain mandatory before every commit.

## Delivery boundary

The spike is complete when:

- the browser distribution installs in pinned Pyodide from same-origin assets;
- native and browser conformance snapshots match;
- the minimal proof validates, formats, and generates JSON Schema;
- all size and timing budgets pass;
- the combined Pages artifact contains both documentation and the proof;
- CI covers the complete gate; and
- documentation records the measured runtime and asset values.

After completion, archive this spec and its implementation plan. Only then
should the project decide whether to proceed to the editor MVP from the broader
playground architecture.

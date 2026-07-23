# 2026-07-22 Playground Local AI — Design

## Status

Shipped on 2026-07-22.

Execution was broken into reviewable tasks in the
[Playground Local AI implementation plan](../plans/2026-07-22-playground-local-ai.md).

This specification defines Phase 6 of the
[Modelable Playground Architecture](../../playground-design.md). It builds on
the shipped multi-file workspace, browser language services, visualization, and
analysis views to add local AI-assisted generation and explanation through
WebLLM, with validated preview and explicit user acceptance for all mutating
actions.

## Context

The Playground is a fully static, browser-native IDE. Parsing, validation,
compilation, visualization, and analysis execute locally via Pyodide. The CLI
already has an `llm` module (`modelable.llm`) with `LLMRequest`, `LLMResponse`,
and `LLMProvider` types, plus engines for entity generation, model explanation,
projection suggestion, update planning, import, and governance recommendation.

None of this is wired to the browser. The browser compiler worker dispatches
synchronous Python calls. AI inference is inherently asynchronous (model
download, GPU warmup, token generation), so the existing synchronous
`dispatch_browser_request` boundary cannot invoke an LLM provider directly.

## Goals

- Add WebLLM model download with progress reporting and explicit user action.
- Add a provider selection and status UI in the Playground toolbar.
- Introduce an async LLM request/response bridge between Python and TypeScript
  so the compiler worker can construct typed LLM requests that TypeScript
  fulfills through the selected provider.
- Implement initial AI actions: generate entity, explain model/diagnostic,
  and suggest projection.
- Every mutating action must produce a preview, show a diff, validate the
  result, and require explicit user acceptance before modifying the workspace.
- Record provider and model metadata in local provenance.
- Preserve the static, local-only, same-origin, no-credentials deployment.
- Maintain existing conformance, performance, and security gates.

## Non-goals

This phase does not include:

- Ollama or remote BYOK provider integration (future provider work);
- service-worker installation or offline model caching (Phase 7);
- streaming token display during generation;
- apply natural-language model update (requires the full update planner);
- import external schema via AI (requires importer infrastructure);
- recommend governance metadata via AI;
- plugin contracts or extension boundaries (Phase 8);
- persisting AI conversation history in IndexedDB;
- changing Modelable parsing, validation, formatting, compilation, registry,
  or compatibility semantics; or
- modifying the CLI `llm` module behavior.

## Chosen approach

### Async LLM bridge

The compiler worker runs Python synchronously. To support async LLM inference,
the protocol gains a new response type: `ai.pending`. When Python needs an LLM
completion, it constructs a typed `LLMRequest` and returns it as a pending AI
request instead of a final result. TypeScript intercepts this, invokes the
selected provider, and re-dispatches the original method with the LLM response
attached. Python then validates and applies the AI output, returning the final
result.

Protocol additions:

```
method: "ai.generate"
payload: { workspaceRevision, action, parameters }

method: "ai.explain"
payload: { workspaceRevision, action, parameters }
```

The `action` field selects the AI operation. `parameters` is action-specific.

When the Python dispatcher receives an `ai.generate` or `ai.explain` request,
it:

1. Builds the system and user prompts from workspace context.
2. Returns a response with `status: "pending_llm"` containing the
   `LLMRequest` (system, user, temperature, responseFormat).
3. TypeScript invokes the provider and re-dispatches with `llmResponse`
   attached to the payload.
4. Python receives the completed response, validates/parses it, and returns
   the final result.

This two-phase dispatch avoids modifying the synchronous Python/Pyodide
boundary while keeping all prompt construction and output validation in Python.

### Provider architecture

```ts
interface LlmRequest {
  system: string;
  user: string;
  temperature: number;
  responseFormat: 'text' | 'json';
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

The initial provider is `WebGpuProvider`, which runs WebLLM in a dedicated Web
Worker using WebGPU. Model download starts only after explicit user action.
Progress is reported to the UI during download and initialization.

The `HeuristicProvider` provides deterministic non-LLM fallback behavior for
entity generation (scaffold from name) and explanation (render compiler output).
It requires no model download and works without WebGPU.

### AI actions

**Generate entity** (`ai.generate`, action: `"generate_entity"`):
- Parameters: `{ description: string, domainName?: string, modelName?: string }`
- Python builds prompts from the workspace summary and description.
- The LLM returns `.mdl` source text.
- Python parses, validates, and returns the proposed source with diagnostics.
- The UI shows a diff preview. The user accepts or discards.

**Explain model/diagnostic** (`ai.explain`, action: `"explain"`):
- Parameters: `{ ref?: string, diagnosticIndex?: number }`
- Python builds context from the referenced model or diagnostic.
- The LLM returns a natural-language explanation.
- The UI displays the explanation in a read-only panel. No workspace mutation.

**Suggest projection** (`ai.generate`, action: `"suggest_projection"`):
- Parameters: `{ sourceRef: string, consumerDomain: string }`
- Python builds prompts from the source model and consumer domain.
- The LLM returns `.mdl` projection source.
- Python parses, validates, and returns the proposed source with diagnostics.
- The UI shows a diff preview. The user accepts or discards.

### WebLLM worker

WebLLM runs in a separate Web Worker (`ai.worker.ts`) to avoid blocking the
main thread during model loading and inference. The worker:

- Imports `@mlc-ai/web-llm`.
- Downloads model assets after receiving an `initialize` message.
- Reports download progress via `postMessage`.
- Handles `complete` messages by running inference and returning the response.
- Handles `dispose` messages by releasing GPU resources.

The main thread communicates with the AI worker through a typed
`AiWorkerClient` that mirrors the `LlmProvider` interface.

### UI components

**AI toolbar section** in the main toolbar:
- Provider status indicator (not ready / downloading / ready / error).
- Model download button (appears when WebGPU is available and no model loaded).
- Download progress bar during model download.

**AI action buttons** in the source editor toolbar:
- "Generate Entity" button opens a prompt input.
- "Explain" button available when cursor is on a model or diagnostic.
- "Suggest Projection" button available when cursor is on a model.
- All buttons disabled when no provider is ready.

**AI preview panel**:
- Shows proposed `.mdl` source with syntax highlighting.
- Shows a textual diff against the current workspace.
- Shows validation diagnostics for the proposed change.
- "Accept" button applies the change to the workspace.
- "Discard" button closes the preview.
- Records provider/model metadata as provenance when accepted.

### Python browser module additions

New file `cli/src/modelable/browser/ai.py`:
- `build_generate_entity_request(workspace, description, domain, name) -> LLMRequest`
- `build_explain_request(workspace, ref, diagnostic_index) -> LLMRequest`
- `build_suggest_projection_request(workspace, source_ref, consumer_domain) -> LLMRequest`
- `parse_generate_result(workspace, content) -> BrowserAiGenerateResult`
- `parse_explain_result(content) -> BrowserAiExplainResult`
- `parse_suggest_result(workspace, content) -> BrowserAiGenerateResult`

New DTOs in `cli/src/modelable/browser/dto.py`:
- `BrowserLlmRequest` matching the TypeScript `LlmRequest`
- `BrowserAiGenerateResult` with proposed source, diagnostics, and diff
- `BrowserAiExplainResult` with explanation text

New dispatch methods in `cli/src/modelable/browser/dispatch.py`:
- `ai.generate` and `ai.explain` with two-phase pending/complete dispatch

### Security boundaries

- No credentials are stored, transmitted, or required.
- WebLLM model assets are fetched from the WebLLM CDN over HTTPS.
- AI-generated content is never applied without explicit user acceptance.
- Generated `.mdl` source is parsed and validated through the same compiler
  pipeline as user-authored source.
- The `HeuristicProvider` never makes network requests.

### Performance budgets

- Model download progress must update at least every 2 seconds.
- AI worker initialization must not block the main thread.
- First-token latency after model load is provider-dependent and not budgeted.
- The AI preview panel must render within 100ms of receiving the result.
- WebGPU capability detection must complete within 50ms.

## Alternatives considered

### Run WebLLM in the compiler worker

Running WebLLM inside the Pyodide worker would avoid the two-phase dispatch but
would block all compiler operations during inference. The dedicated AI worker
keeps the compiler responsive.

### Use transformers.js instead of WebLLM

Transformers.js uses WebAssembly ONNX runtime rather than WebGPU. WebLLM's
WebGPU backend provides better performance for LLM inference on supported
hardware while the heuristic provider covers the fallback case.

### Skip the heuristic provider

Requiring WebGPU would exclude users without compatible hardware. The
heuristic provider ensures basic entity generation and explanation work
everywhere, with AI enhancement as a progressive capability.

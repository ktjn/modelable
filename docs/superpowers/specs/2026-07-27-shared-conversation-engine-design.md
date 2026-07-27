# Shared Conversation Engine — Design

**Date:** 2026-07-27

## Status

Approved in design and written-spec review on 2026-07-27. Implementation is
tracked in the [Shared Conversation Engine plan](../plans/2026-07-27-shared-conversation-engine.md).

This design supersedes the browser-specific raw-source generation path from the
shipped [Playground Local AI design](archived/2026-07-22-playground-local-ai-design.md)
while preserving its local-first, preview-before-apply, and explicit model
download constraints. It aligns the playground with the shipped
[VS Code Conversational Foundation](archived/2026-07-18-vscode-conversational-foundation-design.md)
and the CLI conversation surface.

## Summary

Modelable will use one Python-owned conversation engine across the CLI, VS Code,
and browser playground. The engine will own typed planning, history, focused
definitions, validation, preview state, refinement, and apply/discard
semantics. Each interface will provide only its platform-specific transport,
presentation, and effect adapters.

The browser will stop asking WebLLM to generate raw `.mdl` source. Models will
return closed, schema-constrained conversation plans. Python will validate those
plans and render canonical Modelable source, so punctuation and brace correctness
are no longer delegated to a probabilistic model.

## Context and Current Failure Modes

The shipped conversation surfaces have diverged:

- CLI and VS Code share `ConversationSession`, the closed conversation-plan
  schema, bounded response repair, validated previews, and explicit
  apply/discard behavior.
- The playground uses separate `ai.generate` and `ai.explain` methods. Every
  free-form chat message is routed as `generate_entity`.
- The playground's Suggest Projection shortcut sends empty parameters even
  though Python requires both `sourceRef` and `consumerDomain`.
- Browser generation requests use unconstrained text output and expect the
  model to produce complete `.mdl` source.
- The browser heuristic provider echoes prompts rather than simulating useful
  conversation behavior.
- `LlmRequest.schema` exists in the TypeScript provider contract but is not
  carried through the browser protocol or passed to WebLLM.
- The Ollama adapter requests generic JSON mode instead of passing the closed
  schema already supplied by the shared planner.

An empirical run of the current browser prompts against the local Ollama server
confirmed that this is a contract problem rather than a WebLLM-only rendering
bug. Both `phi3.5:latest` and `qwen2.5-coder:14b` returned invalid Modelable for
entity or projection generation. The outputs omitted required domain structure,
used non-Modelable field syntax, or invented projection grammar.

## Goals

- Use one canonical conversation engine and feature model across CLI, VS Code,
  and the playground.
- Keep interface-specific presentation and effects outside the engine.
- Replace raw-source LLM generation with closed typed plans and canonical
  Python rendering.
- Support the same grounded questions, source changes, projection changes,
  clarification, refinement, compilation, preview, apply, and discard lifecycle
  on all three surfaces.
- Preserve browser-local execution through Pyodide and WebLLM.
- Support asynchronous browser inference through a resumable planning protocol.
- Pass full JSON schemas to providers that support constrained generation.
- Provide a deterministic semantic simulator for normal tests.
- Provide opt-in real-model conformance tests through a developer-controlled
  local Ollama server.
- Preserve explicit user confirmation for every mutating or artifact-promoting
  action.

## Non-Goals

- Expose Ollama as a selectable provider in the web UI.
- Persist browser conversation history across reloads.
- Stream generated tokens.
- Add remote operations, autonomous tools, registry actions, publishing, or
  deployment.
- Make exact natural-language wording identical across interfaces.
- Change Modelable parsing, validation, compatibility, or compilation
  semantics.
- Make browser code emulate a filesystem merely to reuse filesystem-specific
  implementation details.

## Design Principles

1. **One semantic engine, multiple adapters.** Planning and lifecycle behavior
   must not be reimplemented in TypeScript or per interface.
2. **Models propose typed intent, not source text.** Python owns source syntax,
   rendering, and validation.
3. **Preview exact effects before confirmation.** Apply must promote the exact
   staged source or artifacts that the user reviewed.
4. **Platform effects remain explicit.** Filesystem writes, Monaco updates,
   downloads, LSP requests, and terminal rendering stay outside the core.
5. **Real-model tests supplement deterministic contracts.** Normal tests must
   remain fast and reproducible.

## Architecture Decision Scope

No ADR change is required. This design preserves the existing architectural
decisions that Python owns Modelable semantics, validation, planning, and
workspace mutation while TypeScript interfaces own presentation and transport.
It also preserves local browser inference and explicit confirmation boundaries.
The work extracts a shared application-service boundary and adds environment
adapters; it does not introduce a new system dependency, persistence model,
deployment topology, or trust boundary.

## Architecture

```text
CLI terminal ───────────────┐
VS Code chat + LSP ─────────┼──> Conversation Engine
Browser chat + Pyodide ─────┘          |
                                       +--> typed planner
                                       +--> query service
                                       +--> preview lifecycle
                                       +--> common replies
                                       |
                        environment adapter ports
                          |                    |
                  filesystem adapter     browser adapter
```

The implementation will separate three layers.

### Resumable planning

The planning layer builds the existing closed `ConversationPlan` request and
validates provider responses. It will expose a resumable state machine:

```text
begin(message, context)
  -> ConversationPlan
  -> PendingCompletion(request_id, llm_request, attempt)

resume(request_id, response_content)
  -> ConversationPlan
  -> PendingCompletion(repair_request_id, llm_request, next_attempt)
```

The existing synchronous `ConversationPlanner.plan()` API remains as a driver
that loops over this state machine with a synchronous `LLMProvider`. This
preserves CLI and VS Code behavior. The browser pauses at
`PendingCompletion`, invokes WebLLM outside Pyodide, and resumes the same
planning operation.

Pending request IDs are opaque, session-scoped, and single-use. A response for
an unknown, superseded, or already-consumed request is rejected.

### Conversation engine

The engine owns:

- session history;
- focused definition;
- pending completion state;
- pending source-change or compilation state;
- deterministic command routing;
- typed plan execution;
- clarification and unsupported replies;
- refinement and replacement rules;
- preview identity;
- stale-state checks;
- apply and discard transitions; and
- the common structured reply.

The engine does not own:

- network calls;
- filesystem paths or writes;
- LSP session registration;
- Monaco models or browser storage;
- download behavior;
- terminal output; or
- VS Code response rendering.

### Environment ports

The engine depends on narrow interfaces for workspace effects.

The workspace port provides:

- current versioned documents;
- a semantic workspace and summary;
- focused-definition resolution;
- deterministic queries;
- source-change preview;
- exact preview fingerprints;
- source-change promotion; and
- workspace refresh after promotion.

The compilation port provides:

- exact artifact staging;
- artifact metadata and previews;
- freshness verification;
- promotion; and
- cleanup or discard.

The filesystem adapter will wrap the existing `WorkspaceEditor`,
`CompilationService`, file transactions, audit records, and reload behavior.
The browser adapter will operate on versioned in-memory documents and staged
artifact bytes. It will not write a virtual filesystem as an intermediate
effect.

## Shared Features and Interface Differences

All interfaces expose:

- grounded workspace summary, ownership, lineage, dependents, indexes,
  compatibility, and validation questions;
- create model and create projection requests;
- append-version and draft updates;
- clarification when ownership, identity, reusable-model, or projection-source
  intent is ambiguous;
- refinement or replacement of a pending proposal;
- local compilation requests;
- validated previews;
- explicit apply and discard;
- typed unsupported and error replies; and
- deterministic commands that work without an LLM.

### CLI

The CLI retains synchronous provider calls, terminal rendering, filesystem
previews, exact writes, and compilation audits.

### VS Code

VS Code retains its thin-client role. The LSP adapter owns workspace selection,
dirty-buffer checks, session registration, editor anchors, and diff documents.

### Browser

The browser interface will:

- route free-form messages through the shared engine;
- keep Generate, Explain, and Suggest Projection as intent shortcuts rather
  than separate semantic operations;
- resolve focus from the active document and cursor through Python language
  services;
- preview source changes as exact before/after virtual documents;
- apply source changes to the versioned in-memory workspace;
- preview compilation artifacts as exact staged bytes;
- promote accepted compilation results to the output panel and download
  collection;
- retain conversation history for the current page session; and
- expose provider/model metadata without persisting prompt contents.

Suggest Projection will ask for clarification when source or consumer domain
cannot be grounded. It will never call model-summary construction with an empty
reference.

## Browser Conversation Protocol

The browser's bespoke `ai.generate` and `ai.explain` flow will be replaced by:

- `conversation.turn`
- `conversation.resume`
- `conversation.apply`
- `conversation.discard`
- `conversation.reset`

`conversation.turn` includes:

- session ID;
- workspace revision;
- message;
- active document URI; and
- optional zero-based cursor position.

It returns either a common conversation reply or a pending completion:

```json
{
  "status": "pending_llm",
  "sessionId": "session-id",
  "requestId": "request-id",
  "attempt": 0,
  "llmRequest": {
    "system": "…",
    "user": "…",
    "temperature": 0.1,
    "responseFormat": "json",
    "schema": {}
  }
}
```

`conversation.resume` carries the session ID, request ID, workspace revision,
and provider response content. It may return a repair request through the same
pending shape.

Apply and discard require the current pending-action ID. Apply also requires the
workspace revision and exact preview fingerprints. Reset invalidates pending
provider requests and staged actions.

## Provider Contract

`LLMRequest.schema` becomes end-to-end rather than advisory.

- WebLLM receives `response_format: {type: "json_object", schema}`.
- Ollama receives the full schema object in `/api/chat`'s `format` field rather
  than the string `"json"`.
- Providers without native schema constraints receive the schema in the system
  prompt and remain subject to the same parser and repair loop.
- The engine always validates provider output independently, even when the
  provider claims schema conformance.

The structured plan contains typed operations such as `create_model`,
`create_projection`, and `add_projection_field`. It never contains raw source
patches or unrestricted paths. Python renders source through the canonical
compiler renderer.

## Error Handling

- Provider transport failures produce typed actionable replies and preserve
  valid session history.
- Invalid structured output triggers the configured bounded repair loop.
- Exhausted repairs report a concise validation summary without exposing
  prompts, workspace source, or provider internals.
- Missing or ambiguous projection context produces clarification.
- Workspace revision or fingerprint changes invalidate stale previews.
- Cancellation invalidates the active pending request and cannot leave a
  half-applied action.
- Duplicate or late completion responses are rejected.
- Preview promotion is atomic within each environment adapter.
- Adapter failures do not allow replies to claim that source or artifacts were
  promoted.

## Deterministic Simulator

The existing heuristic prompt echo will be replaced with a semantic simulator.
It will inspect the typed request contract and return deterministic plans for:

- workspace questions;
- entity creation;
- projection creation;
- model and projection updates;
- compilation;
- clarification;
- an invalid first response followed by a valid repair; and
- provider failure.

The simulator is a provider test double, not a second planner. It does not
implement Modelable editing rules. All returned plans still pass through the
real parser, engine, preview, validation, and adapter lifecycle.

## Testing Strategy

### Shared contract tests

Run one engine behavior suite against filesystem and in-memory adapters:

- deterministic query without provider;
- entity and projection creation;
- model and projection refinement;
- pending-action replacement;
- compilation preview and promotion;
- apply/discard identity checks;
- stale workspace rejection;
- clarification;
- provider failure;
- malformed response and repair; and
- cancellation cleanup.

### Provider tests

- WebLLM worker tests assert that the full schema reaches
  `response_format`, response content is preserved, repair requests are
  resumable, and disposal rejects pending requests.
- Ollama unit tests assert that the full schema is sent in `format`.
- Parser tests validate closed schemas independently of provider behavior.

### Interface tests

- CLI tests retain terminal and filesystem assertions.
- VS Code tests retain LSP lifecycle, dirty-buffer, diff, and rendering
  assertions.
- Browser unit and Playwright tests use the simulator to cover chat, focus,
  projection creation, clarification, refinement, preview, apply, discard,
  compilation artifacts, and reset.

### Opt-in real-model conformance

Ollama tests run only when explicitly enabled and choose the model through an
environment variable. They assert semantic outcomes rather than exact prose:

- a valid typed entity-creation plan;
- a valid typed projection plan with grounded source mappings;
- a valid update plan;
- appropriate clarification for ambiguity; and
- successful repair or an actionable bounded failure.

The suite never downloads models and is excluded from normal CI. A separate
optional WebGPU smoke may exercise a real WebLLM model locally; normal CI does
not require WebGPU or a model download.

## Security and Privacy

- Browser inference remains local through WebLLM.
- Ollama conformance uses only a developer-controlled local endpoint.
- No provider credentials are introduced into the playground.
- Provider responses remain untrusted and pass through closed-schema
  validation.
- Raw patches, arbitrary filesystem paths, shell commands, and remote
  operations remain outside the plan vocabulary.
- Mutating actions require explicit confirmation.
- Logs contain request IDs, timing, provider/model identity, and error classes,
  but not prompts, source contents, or model responses.

## Migration

1. Extract resumable planning while preserving the synchronous planner API and
   existing CLI/VS Code behavior.
2. Introduce the environment ports and move filesystem-specific effects behind
   the filesystem adapter.
3. Add the semantic simulator and shared engine contract suite.
4. Carry the full schema through provider contracts; constrain WebLLM and
   Ollama output.
5. Add the in-memory browser adapter and browser conversation protocol.
6. Move web chat and shortcut controls to the shared engine.
7. Add browser, Ollama, and optional WebLLM conformance tests.
8. Remove the obsolete raw-source browser AI path after parity tests pass.

Each migration step must leave CLI and VS Code behavior green. The browser does
not switch until the shared engine supports source changes, projection
creation, deterministic questions, compilation, preview, apply, discard, and
repair.

## Acceptance Criteria

- CLI, VS Code, and browser use the same typed planner and conversation engine.
- Free-form browser chat no longer routes unconditionally to entity generation.
- Browser Suggest Projection grounds or clarifies source and consumer domain.
- WebLLM and Ollama receive the full closed response schema.
- No LLM-generated raw `.mdl` source is applied or previewed.
- Python renders syntactically valid source from validated typed operations.
- All interfaces preserve exact preview-before-apply behavior.
- Browser compilation promotes exact staged artifacts to output/download state.
- The semantic simulator drives deterministic cross-interface tests.
- Opt-in Ollama tests exercise real entity, projection, update, clarification,
  and repair behavior.
- Existing CLI and VS Code conversation behavior remains compatible.

# VS Code Conversational Foundation — Design

**Date:** 2026-07-18

## 1. Summary

This design adds a native `@modelable` chat participant to the existing VS Code
extension. The participant exposes the conversational workspace-management
behavior already shipped in `modelable chat`: grounded questions, complete
entity and projection creation, compatibility-aware updates, textual previews,
affected-definition explanations, refinement, apply, and discard.

It builds on the archived
[Conversational Workspace Management — Design](archived/2026-07-18-conversational-workspace-management-design.md)
and implements the next authoring slice in the
[roadmap](../../../ROADMAP.md).

The extension remains a thin client. It sends prompts and editor context over a
versioned custom language-server protocol, then renders structured results from
Python. Provider configuration, typed planning, `.mdl` editing, validation,
compatibility analysis, stale detection, atomic writes, rollback, and
post-apply reload remain in the Python process.

## 2. Goals

The first VS Code conversational slice must:

- contribute one native `@modelable` participant to VS Code Chat;
- expose the full shipped CLI conversation surface;
- use the existing Modelable provider and workspace configuration;
- route all planning and workspace changes through the language server;
- preserve the exact preview-before-confirmation and apply-the-previewed-change
  guarantees of the CLI;
- render textual explanations, affected definitions, diagnostics, and exact
  before/after source snapshots;
- use the built-in VS Code diff editor rather than a custom diff renderer;
- infer the workspace from the active `.mdl` document when possible;
- resolve focused definitions in Python from the active document and cursor;
- refuse planning and apply while any `.mdl` buffer in the selected workspace
  is dirty;
- support multi-root windows without guessing between ambiguous workspaces;
- recover per-chat state from VS Code chat history;
- fail clearly against language servers that predate this protocol; and
- keep prompts, responses, diffs, and source contents out of extension logs by
  default.

## 3. Non-Goals

This slice does not:

- add a dedicated sidebar or webview;
- edit unsaved buffers;
- use the VS Code Language Model API as the planner provider;
- compile artifacts conversationally;
- synchronize registries;
- publish contracts or generated artifacts;
- call external catalog, lineage, schema-registry, or deployment services;
- parse `.mdl`, resolve definitions, plan changes, validate changes, or
  generate patches in TypeScript;
- allow autonomous tool invocation; or
- define authorization and audit policy for operational actions.

An optional VS Code Language Model API provider adapter is a separate roadmap
item after this foundation. That adapter must still route model output through
Python-owned typed plan parsing, validation, preview, and workspace editing.
Its transport and authorization design are intentionally deferred.

## 4. User Experience

### 4.1 Entry point

The extension contributes one sticky native participant with the ID
`modelable-vscode.modelable`:

```text
@modelable
```

The participant accepts ordinary natural-language prompts and these explicit
shortcuts:

- `/help`
- `/apply`
- `/discard`
- `/reset`

The existing CLI-only convenience commands do not need one-for-one chat
commands. Natural-language questions and requests use the shared conversation
service, while the four shortcuts cover discovery and proposal lifecycle.
The extension activates for
`onChatParticipant:modelable-vscode.modelable`.

### 4.2 Question flow

For a grounded question, the participant renders the canonical reply text and
adds anchors for referenced definitions when locations are available.
Deterministic questions remain available without an LLM provider, matching the
CLI boundary.

### 4.3 Change flow

For an entity or projection change, the participant renders:

1. summary;
2. assumptions;
3. proposed definitions and operations;
4. changed definitions;
5. affected definitions;
6. compatibility and validation findings;
7. unified textual diff; and
8. the exact change-set identity and available next actions.

The response then exposes:

- **View Diff**
- **Apply change set**
- **Discard**

The Apply button is the explicit confirmation. A second modal confirmation is
not required because the user has already received the complete preview and the
button identifies the action precisely. A later natural-language message
refines or replaces the pending proposal through the shared conversation
service.

### 4.4 Apply result

A successful apply response lists written paths, changed definitions,
compatibility findings, and the new focused reference. File and definition
anchors allow the user to open the affected source directly.

No response may claim that files were written unless Python completed the
atomic write and successfully reloaded the workspace.

## 5. Architecture

The dependency direction is:

```text
VS Code @modelable participant
  -> TypeScript/JavaScript conversation client
  -> custom language-server requests
  -> Python conversation protocol adapter and session registry
  -> ConversationSession
  -> conversational planner
  -> workspace editor
  -> parser, IR, renderer, validator, compatibility and dependency analysis
```

The extension owns presentation and editor integration only:

- participant registration;
- active editor and workspace-folder context collection;
- dirty-buffer discovery;
- request cancellation;
- response rendering;
- command buttons;
- virtual preview documents; and
- invocation of the built-in diff editor.

The extension commands behind response buttons are:

- `modelable.conversation.viewDiff`
- `modelable.conversation.apply`
- `modelable.conversation.discard`
- `modelable.conversation.reset`

Python owns all semantic behavior:

- provider configuration and calls;
- chat history and pending proposal state;
- workspace and focused-definition resolution;
- typed plan parsing and repair;
- deterministic questions;
- edit planning and rendering;
- validation and compatibility analysis;
- affected-definition calculation;
- preview fingerprinting;
- apply, rollback, and reload; and
- structured response construction.

The protocol adapter resolves configuration with the existing
`resolve_llm_config` function and creates the provider with the existing
`build_provider` factory. VS Code does not introduce separate Modelable
provider settings.

Compiler modules remain independent of chat, providers, language-server
transport, and VS Code.

## 6. Capability and Protocol Version

The language server advertises the feature through the `experimental` portion
of its initialize result:

```json
{
  "modelableConversation": {
    "protocolVersion": 1
  }
}
```

The extension enables the participant's management behavior only when
`protocolVersion` is exactly `1`. When the capability is absent or unsupported,
the participant explains that the installed Modelable language server must be
upgraded. It does not optimistically send unknown methods.

Protocol payloads use JSON-compatible primitives. Paths cross the boundary as
file URIs, definition identities use canonical Modelable refs, and every
request includes `protocolVersion: 1`.

## 7. Language-Server Methods

### 7.1 Turn

Method:

```text
modelable/conversation/turn
```

Request:

```json
{
  "protocolVersion": 1,
  "sessionId": "uuid",
  "workspaceUri": "file:///workspace",
  "message": "add a customer entity with address",
  "activeDocumentUri": "file:///workspace/customer.mdl",
  "position": {"line": 12, "character": 4},
  "dirtyDocumentUris": []
}
```

`activeDocumentUri` and `position` are optional. The server creates the session
when `sessionId` is not registered and reuses it on subsequent turns. A reused
session must remain bound to the same workspace URI. Position values use the
zero-based LSP line and character convention.

### 7.2 Apply

Method:

```text
modelable/conversation/apply
```

Request:

```json
{
  "protocolVersion": 1,
  "sessionId": "uuid",
  "changeSetId": "sha256-derived-id",
  "dirtyDocumentUris": []
}
```

The server rejects the request unless the ID matches the session's current
pending proposal. Python then performs its existing source-fingerprint,
deterministic-restaging, atomic-write, rollback, and reload checks.

### 7.3 Discard

Method:

```text
modelable/conversation/discard
```

Request:

```json
{
  "protocolVersion": 1,
  "sessionId": "uuid",
  "changeSetId": "sha256-derived-id"
}
```

Discard also requires the current change-set ID so an old button cannot discard
a newer refined proposal.

### 7.4 Close

Notification:

```text
modelable/conversation/close
```

Payload:

```json
{
  "protocolVersion": 1,
  "sessionId": "uuid"
}
```

Close is idempotent. `/reset` closes the current session and causes the next
turn to generate a new ID. Extension deactivation sends close notifications
for all locally known sessions.

## 8. Structured Reply

All request methods return the same reply envelope:

```json
{
  "protocolVersion": 1,
  "kind": "preview",
  "text": "canonical rendered response",
  "sessionId": "uuid",
  "workspaceUri": "file:///workspace",
  "changeSetId": "sha256-derived-id",
  "focusedRef": "customer.Customer@1",
  "changedDefinitions": [],
  "affectedDefinitions": [],
  "compatibilityFindings": [],
  "diagnostics": [],
  "previewFiles": []
}
```

`kind` is one of:

- `answer`
- `clarification`
- `preview`
- `applied`
- `discarded`
- `unsupported`
- `error`

Changed definitions contain `ref` and `reason`. Affected definitions contain
`ref`, `status`, and `reason`. Compatibility findings contain `ref`, `status`,
and `message`. Diagnostics contain path, line, column, severity, code, and
message using JSON primitives rather than Python or LSP protocol objects.

Each preview file contains:

```json
{
  "uri": "file:///workspace/customer.mdl",
  "existedBefore": true,
  "beforeText": "exact source snapshot",
  "afterText": "exact candidate source"
}
```

The canonical `text` remains suitable for the CLI and simple clients.
Structured fields exist so VS Code can render anchors, findings, and diffs
without parsing prose.

## 9. Chat Session Identity and Lifecycle

The VS Code API supplies participant-specific chat history but no stable public
conversation identifier or chat-close event. The extension therefore:

1. generates a random UUID for the first participant turn;
2. returns it in namespaced `ChatResult.metadata`;
3. recovers it from the latest Modelable response in `ChatContext.history`;
4. includes it in every language-server request; and
5. starts a new ID when metadata is absent, invalid, reset, or cancelled.

Metadata uses this shape:

```json
{
  "modelable": {
    "protocolVersion": 1,
    "sessionId": "uuid",
    "workspaceUri": "file:///workspace",
    "changeSetId": "optional-id"
  }
}
```

The Python registry holds at most 32 sessions. Sessions expire after 30 minutes
without a request. Each request prunes expired sessions; creating a thirty-third
live session evicts the least recently used session. Missing or expired
sessions return a restart response and never reconstruct or apply an earlier
pending proposal.

Because VS Code does not notify participants when a chat closes, idle expiry is
the authoritative cleanup mechanism. Explicit reset and extension deactivation
provide earlier best-effort cleanup.

## 10. Workspace and Focus Resolution

The extension chooses candidate context in this order:

1. the active `.mdl` document;
2. the only workspace folder containing an unambiguous Modelable workspace; or
3. no selection, producing a clarification response.

For an active `.mdl` document, the server finds the nearest ancestor containing
`workspace.mdl`. If no manifest exists, it uses the same effective-root
behavior as the existing language-server index.

The extension sends the active document URI and cursor position. Python
resolves the containing entity or projection from the indexed parsed document.
TypeScript does not scan source text or reproduce Modelable grammar rules.

In a multi-root window, an active `.mdl` document selects its own root. Without
an active model document, more than one candidate root is ambiguous and the
participant asks the user to open a model file rather than guessing.

A session remains bound to its initial workspace. If the active editor moves to
another workspace, the participant asks the user to reset or start a new chat
before sending the prompt.

## 11. Saved-Source Boundary

Before turn or apply, the extension enumerates dirty `.mdl` documents under the
selected workspace and sends their URIs. The server refuses the operation when
the list is non-empty.

The check covers every dirty `.mdl` file in the workspace, not only the active
file, because a question or plan can depend on or affect any definition. This
preserves the existing disk-source fingerprints and avoids creating a second
buffer-aware editing model.

The response lists the blocking files and asks the user to save them before
retrying. The extension may offer VS Code's normal save command, but it must not
save automatically.

Supporting unsaved buffers later requires a separate design for snapshots,
workspace edits, undo, atomicity, and reconciliation with the Python editor.

## 12. Exact Diff Presentation

For each preview, the extension stores both returned snapshots in an in-memory
`TextDocumentContentProvider`, keyed by session ID, change-set ID, file URI, and
side.

**View Diff** invokes VS Code's built-in diff command with two virtual,
read-only documents:

- exact source at preview time;
- exact candidate source.

Using snapshots on both sides prevents the displayed comparison from changing
silently if the disk file changes after preview. New files use an empty
before-document. Preview documents are released when their proposal is
replaced, discarded, applied, reset, expired locally, or the extension
deactivates.

The diff editor is informational. Apply always calls the Python apply request;
the extension never translates snapshots into a `WorkspaceEdit` or writes
source itself.

## 13. Error and Cancellation Behavior

### 13.1 No provider

Deterministic grounded questions remain available. Requests requiring typed LLM
planning return an unsupported response with the same provider configuration
guidance as the CLI.

### 13.2 Dirty sources

Planning and apply write nothing and identify the files that must be saved.

### 13.3 Invalid or stale proposal

Validation errors, changed source fingerprints, restaging differences, wrong
change-set IDs, and missing sessions write nothing. The response explains that
a fresh preview is required.

### 13.4 Language-server restart

The extension may still recover metadata from chat history, but the new server
has no matching session. It returns an expired-session response. The extension
clears local preview documents and starts a fresh session only after telling the
user that pending actions were invalidated.

### 13.5 Cancellation

Cancelling a turn invalidates the extension's local session ID, sends a
best-effort close notification, and uses a new session ID on the next request.
This makes any late provider result unreachable from the chat even if the
underlying provider call cannot be interrupted immediately.

Apply is not presented as cancellable after Python begins the atomic write
sequence. The extension waits for the definitive applied or error response.

### 13.6 Apply failure

Python retains ownership of rollback. The reply does not claim success unless
the resulting workspace reload succeeds.

## 14. Privacy and Logging

Provider secrets remain in environment variables or workspace configuration
read by Python. They never cross the language-server boundary.

The extension's output channel may log:

- protocol version;
- request kind;
- session lifecycle events;
- elapsed time;
- reply kind; and
- sanitized error codes.

It must not log by default:

- prompts;
- conversation history;
- model responses;
- source summaries;
- diffs;
- before/after snapshots;
- provider credentials; or
- full structured diagnostics containing source text.

## 15. Testing Strategy

### 15.1 Python protocol tests

- Advertise protocol version 1.
- Parse every request payload and reject malformed versions and fields.
- Serialize every reply kind using JSON primitives.
- Preserve canonical text and structured preview data.
- Require exact session and change-set IDs for apply and discard.

### 15.2 Python session tests

- Create and reuse a session for one workspace.
- Reject workspace changes within a session.
- Recover questions, previews, refinements, apply, and discard.
- Expire sessions after 30 idle minutes.
- Enforce the 32-session least-recently-used bound.
- Treat close as idempotent.
- Reject dirty workspaces for turn and apply.
- Reject stale and expired previews without writes.

### 15.3 Focus and workspace tests

- Resolve an entity and projection from document URI and cursor.
- Use the active document's root in a multi-root workspace.
- Clarify when multiple roots are ambiguous.
- Work without `workspace.mdl` using the established effective-root behavior.
- Never resolve focus by parsing source in the extension.

### 15.4 Language-server integration tests

With a deterministic stub provider:

1. ask a grounded question;
2. preview a complete entity;
3. inspect structured changed and affected definitions;
4. inspect exact before/after snapshots;
5. refine the proposal;
6. reject the old change-set ID;
7. apply the refined proposal;
8. reload and continue against the updated workspace; and
9. discard a later proposal.

Additional integration cases cover missing providers, invalid plans, dirty
files, stale fingerprints, restart-like missing sessions, rollback-safe
failures, and multi-root isolation.

### 15.5 VS Code extension tests

- Register `@modelable` and its slash commands.
- Recover session metadata from participant history.
- Generate a new UUID when no valid metadata exists.
- Select workspace context from the active `.mdl` document.
- Refuse and list dirty workspace model files.
- Render every reply kind without parsing canonical prose.
- Store and release virtual preview snapshots.
- Open exact before/after snapshots in the built-in diff editor.
- Route Apply and Discard with exact session and change-set IDs.
- Clear local state on reset, cancellation, expired session, and deactivation.
- Preserve existing activation and language-server smoke coverage.

## 16. Verification

Before every implementation commit, run the repository-required CLI gate from
`cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

For extension changes, also run from `vscode/`:

```bash
npm run check
npm run build
npm test
npm run package
```

Documentation changes must pass strict MkDocs build and the repository's
four-phase documentation review.

## 17. Documentation and Roadmap

Implementation updates:

- `vscode/README.md` with `@modelable`, provider, saved-source, preview,
  session, and troubleshooting guidance;
- `docs/cli-reference.md` or a dedicated editor guide with the shared
  conversation behavior and surface-specific differences;
- `docs/architecture.md` with the custom protocol and session boundary;
- `CHANGELOG.md` with the user-visible feature;
- `ROADMAP.md` to mark this foundation shipped after merge; and
- `ROADMAP.md` now to retain the optional VS Code Language Model API provider
  adapter as an explicit future item.

The later native-provider adapter must not bypass Python plan validation or
workspace editing. Conversational compilation, synchronization, publishing,
and external-service actions remain later work with separate authorization,
preview, confirmation, and audit policy.

## 18. Acceptance Criteria

The foundation is complete when a VS Code user can:

1. invoke `@modelable` in a saved Modelable workspace;
2. ask a grounded question and receive an answer from the shared service;
3. request a complete entity or projection and receive the same safe semantic
   plan as the CLI;
4. review canonical text, affected definitions, diagnostics, and exact source
   snapshots;
5. open the exact preview in VS Code's built-in diff editor;
6. refine or discard without changing source files;
7. explicitly apply the exact current change set;
8. receive a successful post-write reload result with file and definition
   links;
9. continue the same chat against the updated workspace;
10. receive clear save, configuration, ambiguity, expiry, and stale-preview
    guidance; and
11. complete the flow without TypeScript parsing, validation, planning, or
    source writes.

## 19. Architecture Decision Record Impact

No ADR change is required. This design preserves the existing local-first
architecture, Python compiler authority, language-server transport, and
preview-before-write safety boundary. The native chat participant and custom
protocol are additive client and application-service interfaces over those
documented decisions; they do not introduce a new deployment model, storage
authority, external operational action, or source-of-truth boundary.

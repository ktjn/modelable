# 2026-08-01 Modelable LSP RAG Adapter Design

## Goal

Expose the shared documentation RAG answer pipeline through the Modelable conversation protocol so VS Code can issue evidence-grounded `/docs <question>` turns without changing ordinary conversation behavior.

## Scope

This slice adds an optional documentation-index capability to `modelable/conversation/turn`. The client may provide a local file URI for the binary Searchable `manifest.json` associated with a new conversation session. The LSP service creates one retriever for that session and routes `/docs` through the existing `documentation_chat_reply` adapter. Normal messages, `/ask`, editing, compilation, apply, discard, and close continue through the existing session paths.

The web playground and Pyodide/Searchable browser integration remain out of scope. The protocol field is additive and optional so existing VS Code clients remain compatible.

## Protocol

Extend `ConversationTurnParams` with:

```json
{
  "documentationIndexUri": "file:///workspace/dist/search-index/manifest.json"
}
```

The value is optional and must be a file URI when present. Protocol version 2 remains unchanged because this is an optional field under the existing `extra="forbid"` model; clients and servers that support this slice understand the field together.

The index URI is session configuration: it is accepted when `createSession` is true and stored with the session. A later turn may omit it, but supplying a different URI for an existing session is rejected with a clear session-configuration error. This prevents a session from silently changing evidence sources mid-conversation.

## Architecture and data flow

`LspConversationService` resolves the optional URI to a local path, requires the resolved manifest path to remain inside the conversation workspace, parses the manifest, and requires every referenced shard to resolve inside that workspace after symlink resolution. Only then does it construct `DocumentationRetriever` once for the new session. The session entry stores the retriever and the canonical index URI.

For each turn:

1. Validate the existing protocol payload and workspace/dirty-document rules.
2. Resolve or validate the session-bound documentation index.
3. If the message is `/docs ...`, call `documentation_chat_reply` with the stored retriever and `ConversationSession.provider`, then wrap the resulting text in a normal `ConversationReply(kind="answer")` for existing serialization.
4. Otherwise call `ConversationSession.turn` exactly as today.

The shared adapter remains responsible for command parsing, retrieval, evidence selection, citations, insufficient evidence, missing-provider guidance, and provider-error rendering. The LSP layer does not duplicate prompt or citation logic.

## Error handling and security

- A non-file `documentationIndexUri` is rejected before session creation.
- A manifest outside the workspace, a shard reference that traverses outside it, or an in-workspace shard symlink whose target is outside it is rejected before retriever construction. This applies to term, document, facet, pin, synonym, fuzzy, and vector shard references.
- An invalid or unreadable manifest is rejected as `ConversationSessionError`; manifests that pass the confinement check still undergo the Searchable client's existing validation during retriever construction.
- `/docs` without an index returns an actionable answer-level message and keeps the session usable.
- Missing providers and provider failures remain answer-level messages through `documentation_chat_reply`; they must not tear down the session.
- Changing the index URI on an existing session is rejected without changing the stored retriever.

## Testing

Add coverage for:

- protocol alias validation and optional `documentationIndexUri` serialization/model behavior;
- new-session index construction and session-bound reuse;
- `/docs` answer text, citations, insufficient evidence, missing provider, and provider failure;
- rejection of non-file and outside-workspace index URIs, traversal shard references, and escaping shard symlinks across every file-bearing manifest section;
- rejection of index changes on an existing session;
- ordinary turns and existing `/ask`/editing behavior remaining unchanged;
- LSP integration request/response shape using the existing serialized conversation reply.

## Compatibility and non-goals

- No protocol version bump and no required client change.
- No new runtime dependency or bundled embedding provider.
- No index copying or per-document files; the configured path remains the single binary Searchable index manifest.
- No web/playground or Pyodide implementation in this slice.

## ADR impact

No ADR is required for this slice.

This change is an additive optional protocol-v2 field that reuses the existing workspace-bound file-URI security boundary and the existing RAG answer architecture. It does not change the deployment model, storage model, ownership boundaries, or responsibility split between clients, the LSP service, and the shared retrieval pipeline. Because the architectural decision record set already covers those underlying decisions and this slice only extends them in-place without changing their constraints, the spec itself is the right level of documentation for this work.

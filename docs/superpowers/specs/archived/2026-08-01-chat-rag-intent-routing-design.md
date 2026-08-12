# 2026-08-01 Modelable Chat RAG Intent Routing Design

## Goal

Integrate documentation retrieval into the normal CLI, VS Code, and Playground chat flow without making every message pay retrieval latency or allowing retrieved documentation to influence mutation planning. Documentation-like questions should receive grounded answers automatically; explicit `/docs <question>` remains the deterministic override.

## Decisions

- Use a deterministic, dependency-free intent router shared by all clients. Do not call an LLM merely to classify intent.
- Classify each message as `documentation`, `workspace`, or `general` with a confidence level and a reason code.
- Route only high-confidence documentation questions to the existing `answer_with_retrieval` pipeline when a documentation index is configured.
- Keep explicit `/docs <question>` as a force-retrieve command, including when automatic retrieval is disabled.
- Never automatically retrieve for mutation, compilation, apply/discard, provider-control, or other slash commands.
- If no documentation index exists, silently use the ordinary chat path; automatic retrieval is an enhancement, not a prerequisite.
- Return typed retrieval metadata (`retrievalUsed`, citations, and route reason) so each client can present citations without parsing answer prose.
- Preserve the existing workspace planner and mutation lifecycle. Retrieved evidence is used only by informational answer turns and is never inserted into a change-set or compile request.
- Default automatic retrieval to enabled when an index is configured, with a client-visible opt-out setting. The explicit `/docs` command bypasses that setting.

## Intent model

The router first normalizes Unicode whitespace and case, then applies safety exclusions before positive signals:

1. Force retrieval when the normalized message starts with `/docs` and has a non-empty question.
2. Return `none` for `/apply`, `/discard`, `/compile`, `/update`, `/reset`, `/exit`, `/quit`, and other slash commands.
3. Return `none` for messages containing clear mutation verbs such as `add`, `change`, `create`, `delete`, `remove`, `rename`, `update`, `generate`, `compile`, or `apply` when they refer to the workspace.
4. Mark a message as automatic documentation intent only when it has at least one documentation signal (`documentation`, `docs`, `guide`, `reference`, `syntax`, `configure`, `configuration`, `command`, `option`, or `how do I`) and no mutation exclusion.
5. Otherwise use the ordinary workspace/general chat path.

The router must expose a pure function with a stable result so the three clients cannot drift:

```python
class RetrievalRoute(StrEnum):
    NONE = "none"
    AUTOMATIC_DOCUMENTATION = "automatic_documentation"
    EXPLICIT_DOCUMENTATION = "explicit_documentation"

@dataclass(frozen=True)
class RetrievalDecision:
    route: RetrievalRoute
    reason: str
    question: str
```

This is intentionally conservative. False negatives continue through ordinary chat; false positives are prevented from reaching mutation planning by the exclusion rules.

## Runtime flow

Each client calls the shared router before its ordinary conversation planner:

```text
message
  -> classify intent
      -> explicit /docs or high-confidence documentation + index configured
          -> retrieve bounded evidence -> LLM answer -> citations
      -> otherwise
          -> existing workspace/general conversation path
```

The shared answer helper receives the extracted question, retriever, provider, and limits. It returns an answer plus structured citations and a retrieval route. Retrieval failures are recoverable: explicit `/docs` returns the existing user-visible documentation error, while automatic retrieval falls back to ordinary chat and does not terminate a session.

## Client behavior

- CLI: `ChatState` keeps its existing retriever and automatic-retrieval setting. Informational answers show the existing source lines; mutation commands retain preview/apply behavior.
- VS Code: `ConversationSessionParams` accepts the automatic-retrieval setting at session creation. Serialized answers include retrieval metadata for the participant renderer; source links remain workspace-safe.
- Playground: the browser session uses the bundled same-origin JSON index. The client renders automatic documentation answers with the existing safe citation component and keeps `/docs` as an explicit override.
- All clients use the same intent decisions and evidence limits. No client implements its own keyword list.

## Safety and performance

- No remote classifier, embedding provider, or new runtime dependency is introduced.
- Retrieval is skipped for mutation-like messages before index access.
- The existing evidence limits remain authoritative: bounded chunks, bounded context words, and lexical retrieval for the current JSON index.
- A failed or missing index never blocks ordinary chat.
- The opt-out setting is session-scoped and does not persist provider secrets, index bytes, or answers.
- Citation URLs are validated/rendered using the existing safe-link rules.

## Testing and rollout

- Unit-test the pure router with positive documentation examples, workspace questions, mutation exclusions, slash commands, Unicode whitespace, and explicit `/docs`.
- Add contract tests proving all three client adapters consume identical route decisions and preserve ordinary planner calls.
- Add CLI/LSP/browser tests for automatic retrieval success, no-index fallback, retrieval failure fallback, explicit override, citation metadata, and mutation non-interference.
- Add a Playground e2e smoke for an automatic documentation question and a mutation question that must not load the docs index.
- Document the behavior and opt-out setting before enabling it by default. Keep the existing explicit `/docs` path as the rollback-safe fallback.

## Non-goals

- No automatic retrieval for mutation or compile requests.
- No vector or hybrid retrieval in this slice.
- No user-supplied remote indexes.
- No extension/plugin registry work; this phase precedes the roadmap's extensibility phase.

No new ADR is required: this design extends the already accepted shared Python chat/RAG boundary and only changes routing policy at the existing client entry points.

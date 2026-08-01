# Task 3 report — CLI and VS Code automatic routing

## Status

Completed Task 3 in `C:\git\modelable\.worktrees\chat-rag-intent-plan` on
`codex/chat-rag-intent-plan`. The change is limited to CLI and LSP routing,
protocol serialization, and the three permitted test files. No browser files or
sibling worktrees were modified.

## Commits

- `aaa5473` — `feat(chat): route documentation questions through RAG`
- This report is included in a follow-up documentation commit on the same branch.

## Focused test output

Command:

```text
uv run pytest tests/test_llm_features.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -k "retrieval or documentation or intent" -q
```

Red step:

```text
5 failed, 14 passed, 1 skipped in 9.76s
```

The expected failures showed that automatic questions still reached the planner,
`automaticDocumentation` was rejected, automatic retrieval was not attempted,
and LSP retrieval metadata was absent.

Final green run:

```text
19 passed, 1 skipped in 7.91s
```

## Full gate output

Commands:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Final run:

```text
uv run ruff format .          -> 1 file reformatted, 305 files left unchanged
uv run ruff check .           -> All checks passed!
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
                               -> mypy baseline ratchet passed: 391 current errors, 51 resolved baseline errors
uv run pytest --tb=short      -> 1694 passed, 22 skipped in 35.95s
```

`git diff --check` also passed before the implementation commit.

## Self-review

- CLI `chat_turn` and LSP session handling classify retrieval intent before
  ordinary slash-command or planner dispatch.
- Automatic documentation uses the shared grounded-answer helper only when both
  a documentation retriever and provider are available. Missing dependencies and
  automatic retrieval/provider failures fall back to the existing ordinary path.
- Explicit `/docs` remains available when automatic routing is disabled and keeps
  its existing blank-question, missing-index, missing-provider, and provider-failure
  responses.
- `automaticDocumentation` is stored per LSP session, defaults to enabled when a
  documentation index is bound, and cannot be changed for an existing session.
  CLI state has the equivalent session-scoped override and otherwise derives the
  default from its configured retriever.
- LSP serialization emits camel-case `retrievalUsed`, `citations`, and
  `routeReason` only for retrieval-backed answer replies. Planner fallbacks and
  mutation replies retain the prior shape.
- Focused coverage includes fake retriever/provider success, no-index planner
  fallback, automatic failure fallback, explicit `/docs` with automatic disabled,
  mutation exclusion, retrieval metadata, and a real JSON-RPC automatic-routing
  integration test.

## Concerns

- Automatic retrieval failures are intentionally silent and fall back to ordinary
  chat, as required. This preserves the session but means users do not receive a
  retrieval-specific diagnostic for automatic routes.
- No unresolved test, typing, scope, or browser-surface concerns remain.

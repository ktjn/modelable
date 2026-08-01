# Task 2 report — reusable grounded answer and reply metadata

## Status

Completed Task 2 in `C:\git\modelable\.worktrees\chat-rag-intent-plan` without modifying client entry points.

## Commit(s)

- `66d253d` — `feat(rag): expose structured grounded answer metadata`
- This report is included in the current HEAD on top of that implementation commit.

## Focused test output

Command:

```text
uv run pytest tests/test_rag_generation.py tests/test_llm_features.py -k "retrieval or citation or reply" -q
```

Red step:

```text
.FF
FAILED tests/test_rag_generation.py::test_answer_calls_provider_and_appends_structured_citations
FAILED tests/test_llm_features.py::test_conversation_reply_defaults_keep_minimal_answer_construction_valid
```

Green step:

```text
...
3 passed in 3.34s
```

## Full gate output

Commands:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Final clean run:

```text
uv run ruff format .          -> 306 files left unchanged
uv run ruff check .           -> All checks passed!
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
                               -> mypy baseline ratchet passed: 391 current errors, 51 resolved baseline errors
uv run pytest --tb=short      -> 1684 passed, 22 skipped in 18.66s
```

## Self-review

- `RagAnswer` now carries `retrieval_used` and `route_reason` alongside answer text and structured citations.
- `answer_with_retrieval()` remains the shared bounded retrieval helper and preserves the existing `Sources:` answer text shape for explicit `/docs` callers.
- `ConversationReply` now accepts defaulted `citations`, `retrieval_used`, and `route_reason`, so existing minimal construction remains valid.
- No CLI, LSP, or browser entry-point routing behavior was changed in this task.
- The diff is limited to the required generation/backend/test files plus this report.

## Concerns

- `ConversationReply` now stores retrieval metadata, but this task intentionally does not serialize or render it through client entry points yet; that follow-through belongs to the later routing/integration tasks.

## Fix round 1

### Status

Addressed the review finding that browser dispatch was leaking Task 2 retrieval metadata into every ordinary reply payload.

### Changed files

- `cli/src/modelable/llm/conversation_backend.py`
- `cli/src/modelable/browser/dispatch.py`
- `cli/tests/test_browser_api.py`
- `cli/tests/test_llm_features.py`

### Focused tests and outputs

Command:

```text
uv run pytest tests/test_rag_generation.py tests/test_llm_features.py tests/test_browser_api.py -k "retrieval or citation or reply or conversation_turn" -q
```

First run:

```text
....F
FAILED tests/test_browser_api.py::test_dispatch_conversation_turn_includes_retrieval_metadata_only_for_grounded_answers
TypeError: Object of type RagCitation is not JSON serializable
```

Final run:

```text
.....
5 passed in 4.11s
```

### Full gate outputs

Commands:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Final clean run:

```text
uv run ruff format .          -> 1 file reformatted, 305 files left unchanged
uv run ruff check .           -> All checks passed!
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
                               -> mypy baseline ratchet passed: 391 current errors, 51 resolved baseline errors
uv run pytest --tb=short      -> 1686 passed, 22 skipped in 18.75s
```

### Fix summary

- Moved retrieval metadata behind optional `ConversationReply.retrieval` storage plus compatibility accessors, so ordinary replies keep the same browser wire shape.
- Replaced browser conversation reply `asdict()` serialization with a custom serializer that omits retrieval fields for ordinary replies and includes structured metadata only for retrieval-backed answers.
- Added a dispatch-level regression proving ordinary `conversation.turn` replies omit the new keys, plus a retrieval-backed case that includes them only when present.

### Commit hash

- Pending fix commit hash; recorded in the follow-up report update commit.

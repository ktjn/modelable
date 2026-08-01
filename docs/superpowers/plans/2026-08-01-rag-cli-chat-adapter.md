# Modelable CLI RAG Chat Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in `/docs <question>` support to `modelable llm chat` using the existing binary Searchable index and shared RAG answer pipeline.

**Architecture:** Add one command adapter in `modelable.llm.chat` that recognizes `/docs` messages and delegates to `answer_with_retrieval`. The CLI command constructs one `DocumentationRetriever` from a new `--docs-index` option and uses the adapter for both single-message and interactive paths; ordinary messages remain on `ConversationSession`.

**Tech Stack:** Python 3.11+, Click, pytest, existing `searchable-client`, Modelable `LLMProvider` and RAG modules.

## Global Constraints

- The documentation index is the single binary Searchable index manifest accepted by `DocumentationRetriever`.
- The feature is opt-in; without `--docs-index`, existing chat behavior is unchanged.
- Do not add a bundled embedding provider or a new runtime dependency.
- Reuse `answer_with_retrieval` for retrieval, context selection, prompt construction, citations, and insufficient-evidence behavior.
- Before a PR, run from `cli/`: `uv run ruff format .`, `uv run ruff check .`, `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, and `uv run pytest --tb=short`.

---

### Task 1: Add the shared `/docs` chat-command adapter

**Files:**
- Modify: `cli/src/modelable/llm/chat.py`
- Test: `cli/tests/test_conversation.py`

**Interfaces:**
- Consumes: `DocumentationRetriever`, `LLMProvider | None`, and a command string.
- Produces: `documentation_chat_reply(command_text, retriever, provider) -> str | None`; returns `None` for non-`/docs` messages and a rendered answer or actionable command error for `/docs` messages.

- [ ] **Step 1: Write the failing tests**

Add tests alongside the existing `chat_turn` command tests. Use the existing `make_index` pattern from `cli/tests/test_cli_docs_ask.py` or a small fake retriever/provider, and assert the shared answer shape rather than a duplicated prompt.

```python
def test_docs_chat_uses_rag_answer_and_sources(tmp_path: Path) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    state = ChatState(docs_retriever=DocumentationRetriever(index))

    response = chat_turn(
        load_workspace(tmp_path),
        "/docs how do I install it?",
        path=tmp_path,
        state=state,
        provider=FakeProvider(),
    )

    assert "[S1]" in response
    assert "guide.md#install" in response


def test_docs_chat_requires_configured_index(tmp_path: Path) -> None:
    state = ChatState()
    response = chat_turn(load_workspace(tmp_path), "/docs install", path=tmp_path, state=state)
    assert "--docs-index" in response


def test_docs_chat_preserves_normal_conversation(tmp_path: Path) -> None:
    provider = QueueProvider("normal response")
    state = ChatState(docs_retriever=FakeRetriever([]))
    response = chat_turn(load_workspace(tmp_path), "summarize this workspace", path=tmp_path, state=state, provider=provider)
    assert response == "normal response"
```

The exact fixtures should follow the existing provider/retriever test helpers already used in this repository.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run from `cli/`:

```bash
uv run pytest tests/test_conversation.py -k "docs_chat" -q
```

Expected: FAIL because `ChatState` has no documentation retriever and `/docs` is not recognized.

- [ ] **Step 3: Implement the minimal adapter**

Extend `ChatState` with an optional `DocumentationRetriever`. Add:

```python
def documentation_chat_reply(
    command_text: str,
    *,
    retriever: DocumentationRetriever | None,
    provider: LLMProvider | None,
) -> str | None:
```

The function must:

1. Return `None` when the first shell-parsed command is not `docs`.
2. Return `"Provide a question after /docs."` for a blank question.
3. Return a message containing `--docs-index` when the retriever is absent.
4. Call `answer_with_retrieval(retriever, provider, question)` and return `RagAnswer.answer` otherwise.

Call this adapter before the existing generic command branch in `_chat_turn`. Add `/docs <question>` to `chat_help()`. Do not change `/ask` semantics.

- [ ] **Step 4: Run the focused tests to verify they pass**

```bash
uv run pytest tests/test_conversation.py -k "docs_chat" -q
```

Expected: PASS.

- [ ] **Step 5: Commit the shared adapter**

```bash
git add cli/src/modelable/llm/chat.py cli/tests/test_conversation.py
git commit -m "feat: add documentation RAG chat command"
```

### Task 2: Wire `--docs-index` into the CLI chat command

**Files:**
- Modify: `cli/src/modelable/commands/llm.py`
- Test: `cli/tests/test_cli_docs_ask.py` or the existing CLI/provider integration test module selected after locating the chat command tests

**Interfaces:**
- Consumes: `--docs-index PATH`, `DocumentationRetriever`, and `documentation_chat_reply`.
- Produces: `modelable llm chat --docs-index PATH` support for both `--message "/docs ..."` and interactive input.

- [ ] **Step 1: Write the failing CLI tests**

Add Click runner coverage that monkeypatches `build_provider` with the existing fake provider and invokes the registered CLI command. Cover both one-shot and interactive input:

```python
def test_llm_chat_docs_message_uses_index(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())

    result = runner.invoke(cli, ["llm", "chat", "--path", str(tmp_path), "--docs-index", str(index), "--message", "/docs install"])

    assert result.exit_code == 0, result.output
    assert "guide.md#install" in result.output


def test_llm_chat_docs_without_index_explains_configuration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())
    result = runner.invoke(cli, ["llm", "chat", "--path", str(tmp_path), "--message", "/docs install"])
    assert result.exit_code == 0, result.output
    assert "--docs-index" in result.output
```

Also verify ordinary `--message` input still reaches the session when `--docs-index` is present.

- [ ] **Step 2: Run the focused CLI tests to verify they fail**

```bash
uv run pytest tests/test_cli_docs_ask.py -k "llm_chat_docs" -q
```

Expected: FAIL because the chat command does not define `--docs-index` or dispatch `/docs`.

- [ ] **Step 3: Implement CLI wiring**

In `cli/src/modelable/commands/llm.py`:

1. Add `@click.option("--docs-index", type=click.Path(exists=True, path_type=Path), default=None, help="Binary documentation Searchable index manifest.")`.
2. Construct `DocumentationRetriever(docs_index)` once after provider configuration when the option is present.
3. For `--message`, call `documentation_chat_reply` before `session.turn`; print its result when it returns a string.
4. In the interactive loop, call the same adapter before `session.turn`.
5. Preserve `/exit`, `/quit`, `/help`, cleanup, and provider error behavior.

The command should pass the retriever into `ChatState` only if the implementation routes through `chat_turn`; otherwise use the shared adapter directly and keep the existing `ConversationSession` lifecycle unchanged. Do not create a second retriever per question.

- [ ] **Step 4: Run the focused CLI tests to verify they pass**

```bash
uv run pytest tests/test_cli_docs_ask.py -k "llm_chat_docs" -q
```

Expected: PASS.

- [ ] **Step 5: Run the relevant regression tests**

```bash
uv run pytest tests/test_conversation.py tests/test_cli_docs_ask.py tests/test_llm_provider_integration.py --tb=short
```

Expected: PASS with no changes to existing `/ask`, provider, session cleanup, or command authorization tests.

- [ ] **Step 6: Commit the CLI wiring**

```bash
git add cli/src/modelable/commands/llm.py cli/tests/test_cli_docs_ask.py
git commit -m "feat: expose documentation RAG in llm chat"
```

### Task 3: Update user-facing documentation and verify the full gate

**Files:**
- Modify: `docs/cli-reference.md`
- Test: `cli/tests/test_cli.py` or the existing documentation/help test if command help is snapshot-tested

**Interfaces:**
- Consumes: the completed `--docs-index` and `/docs` CLI behavior.
- Produces: documentation that shows the binary index path and the opt-in command without implying that normal chat automatically uses RAG.

- [ ] **Step 1: Add the usage example and help assertion**

Document:

```text
modelable llm chat --path ./workspace --docs-index ./docs-index/manifest.json
you> /docs How do I configure the registry?
```

State that `/docs` is evidence-grounded and citations come from the configured index. Add or update the existing help assertion to include `/docs <question>`.

- [ ] **Step 2: Run the documentation-specific checks**

```bash
uv run pytest tests/test_cli.py tests/test_conversation.py -k "help or docs" --tb=short
```

Expected: PASS.

- [ ] **Step 3: Run all required Modelable gates from `cli/`**

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass cleanly. If formatting changes files, review them and include only intended changes before committing.

- [ ] **Step 4: Run strict documentation validation**

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: successful strict build with no warnings.

- [ ] **Step 5: Review and commit the documentation/gate result**

```bash
git status --short
git diff --check
git add docs cli
git commit -m "docs: document CLI documentation RAG chat"
```

The branch is ready for review only after the four `cli/` gates and strict docs build have passed.

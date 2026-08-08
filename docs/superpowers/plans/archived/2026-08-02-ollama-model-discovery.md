# Ollama Model Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a CLI user list the models installed on their local Ollama
server (`modelable models`), instead of having to already know the exact
model tag before running `chat`/`update`/`docs-ask` with `--provider ollama`.

**Architecture:** Add a `list_ollama_models(base_url, timeout)` function to
`cli/src/modelable/llm/providers.py` that calls Ollama's `GET /api/tags` and
returns installed model names. Expose it as a new top-level `modelable
models` Click command in `cli/src/modelable/commands/llm.py`. No changes to
`build_provider` or `resolve_llm_config` — a model is still required
explicitly wherever it's required today.

**Tech Stack:** Python 3.14, `urllib.request` (stdlib, no new dependency,
matches the existing `OllamaProvider`/`AnthropicProvider` transport style),
Click, pytest with `pytest-xdist` (tests run under `-n auto` by default in
this repo — avoid shared mutable state between tests), `rich.console.Console`
for output.

## Global Constraints

- Scope is Ollama only — no other local backend, no OpenAI-compatible
  abstraction (per spec Non-goals).
- `--provider ollama` continues to require an explicit model (`--model`,
  `MODELABLE_LLM_MODEL`, or workspace `ai.model`); discovery introduces no
  auto-selection or fallback behavior (per spec Goals).
- Base URL resolution for the new command must match existing resolution
  order: flag → `MODELABLE_LLM_BASE_URL` → `OLLAMA_HOST` → default
  `http://localhost:11434` (already implemented in `resolve_llm_config` /
  `build_provider`; reuse it, don't reimplement).
- Follow existing code style in the two files touched: dataclass-free plain
  functions in `providers.py`, `error.HTTPError`/`error.URLError` →
  `RuntimeError` translation matching `_post_json`'s existing message format
  (`"Ollama request failed: <detail>"`).
- Before committing any Python change: run `uv run ruff format`, `uv run
  ruff check`, the mypy baseline ratchet, and the relevant pytest file(s),
  from the `cli/` directory (this project's pre-commit convention — see
  `docs/superpowers/specs/2026-08-02-ollama-model-discovery-design.md`).
- Ollama is running locally on this machine (confirmed by the user) at the
  default `http://localhost:11434` — usable for manual verification and for
  the opt-in conformance test in Task 4.

---

### Task 1: `list_ollama_models` function + unit tests

**Files:**
- Modify: `cli/src/modelable/llm/providers.py` (add function after the
  `OllamaProvider` class, before `build_provider`)
- Test: `cli/tests/test_llm_provider_integration.py`

**Interfaces:**
- Produces: `list_ollama_models(base_url: str, timeout: float = 10.0) ->
  list[str]` in `modelable.llm.providers`. Raises `RuntimeError` on
  connection failure, HTTP error, or invalid JSON. Returns model names
  sorted alphabetically (empty list if none installed).

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_llm_provider_integration.py`. First, extend the
existing import line (currently `from modelable.llm.providers import
LLMRequest, LLMResponse, OllamaProvider, build_provider`) to also import
`list_ollama_models`:

```python
from modelable.llm.providers import LLMRequest, LLMResponse, OllamaProvider, build_provider, list_ollama_models
```

Then add these four tests (place them near the other `OllamaProvider` tests,
e.g. after `test_ollama_provider_posts_full_json_schema`):

```python
def test_list_ollama_models_parses_multi_model_response(monkeypatch):
    class DummyResponse:
        def read(self) -> bytes:
            return json.dumps(
                {"models": [{"name": "qwen2.5-coder:14b"}, {"name": "llama3.2"}]}
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured: dict[str, object] = {}

    def fake_urlopen(req: request.Request, timeout: float):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    names = list_ollama_models("http://localhost:11434")
    assert names == ["llama3.2", "qwen2.5-coder:14b"]
    assert captured["url"] == "http://localhost:11434/api/tags"
    assert captured["method"] == "GET"
    assert captured["timeout"] == 10.0


def test_list_ollama_models_returns_empty_list_when_none_installed(monkeypatch):
    class DummyResponse:
        def read(self) -> bytes:
            return json.dumps({"models": []}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req: request.Request, timeout: float):
        return DummyResponse()

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    assert list_ollama_models("http://localhost:11434") == []


def test_list_ollama_models_raises_runtime_error_on_connection_failure(monkeypatch):
    from urllib import error as urllib_error

    def fake_urlopen(req: request.Request, timeout: float):
        raise urllib_error.URLError("Connection refused")

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Ollama request failed: Connection refused"):
        list_ollama_models("http://localhost:11434")


def test_list_ollama_models_raises_runtime_error_on_http_error(monkeypatch):
    from urllib import error as urllib_error

    def fake_urlopen(req: request.Request, timeout: float):
        raise urllib_error.HTTPError(
            "http://localhost:11434/api/tags", 500, "Internal Server Error", {}, io.BytesIO(b"boom")
        )

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Ollama request failed: 500 boom"):
        list_ollama_models("http://localhost:11434")
```

The `HTTPError` test needs `io.BytesIO` (its `read()` mock body). The file's
current import block (top of file) is:

```python
from __future__ import annotations

import json
from pathlib import Path
from urllib import request

import pytest
from click.testing import CliRunner
```

Add `import io` alongside `import json`, so the block reads:

```python
import io
import json
from pathlib import Path
from urllib import request
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_llm_provider_integration.py -k list_ollama_models -v`
Expected: FAIL with `ImportError: cannot import name 'list_ollama_models'`

- [ ] **Step 3: Implement `list_ollama_models`**

In `cli/src/modelable/llm/providers.py`, add this function directly after
the `OllamaProvider` class's `_post_json` method (i.e. after the class body
ends, before `def build_provider(...)`):

```python
def list_ollama_models(base_url: str, timeout: float = 10.0) -> list[str]:
    req = request.Request(base_url.rstrip("/") + "/api/tags", method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:  # pragma: no cover - thin transport wrapper
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:  # pragma: no cover - thin transport wrapper
        raise RuntimeError(f"Ollama request failed: {exc.reason}") from exc

    try:
        payload = cast(dict[str, object], json.loads(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc

    models = payload.get("models")
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for entry in models:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str):
                names.append(name)
    return sorted(names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_llm_provider_integration.py -k list_ollama_models -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run ruff and mypy, then the full provider test file**

Run:
```bash
cd cli
uv run ruff format src/modelable/llm/providers.py tests/test_llm_provider_integration.py
uv run ruff check src/modelable/llm/providers.py tests/test_llm_provider_integration.py
uv run mypy src/modelable/llm/providers.py
uv run pytest tests/test_llm_provider_integration.py -v
```
Expected: ruff and mypy report no new issues, all tests in the file pass
(the file had 36 passing tests before this task; expect 40 after).

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/llm/providers.py cli/tests/test_llm_provider_integration.py
git commit -m "feat(llm): add list_ollama_models to probe installed Ollama models"
```

---

### Task 2: `modelable models` CLI command + unit tests

**Files:**
- Modify: `cli/src/modelable/commands/llm.py` (add `import` of
  `list_ollama_models`, add `models` command, register it in
  `register_llm_commands`)
- Test: `cli/tests/test_llm_provider_integration.py`

**Interfaces:**
- Consumes: `list_ollama_models(base_url: str, timeout: float = 10.0) ->
  list[str]` and `resolve_llm_config(...)` (existing, from
  `modelable.llm.config`, already imported in `commands/llm.py`) from Task 1.
- Produces: `modelable models [--base-url URL]` CLI command.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_llm_provider_integration.py` (this file already
imports `CliRunner` and `cli` — check the top of the file for `from
click.testing import CliRunner` and `from modelable.cli import cli`, both
already present per the existing chat-command tests in this file):

```python
def test_models_command_lists_installed_models(monkeypatch):
    class DummyResponse:
        def read(self) -> bytes:
            return json.dumps({"models": [{"name": "llama3.2"}, {"name": "codellama"}]}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req: request.Request, timeout: float):
        return DummyResponse()

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    result = CliRunner().invoke(cli, ["models"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["codellama", "llama3.2"]


def test_models_command_reports_hint_when_none_installed(monkeypatch):
    class DummyResponse:
        def read(self) -> bytes:
            return json.dumps({"models": []}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req: request.Request, timeout: float):
        return DummyResponse()

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    result = CliRunner().invoke(cli, ["models"])
    assert result.exit_code == 0, result.output
    assert "No models installed" in result.output
    assert "ollama pull" in result.output


def test_models_command_reports_connection_failure(monkeypatch):
    from urllib import error as urllib_error

    def fake_urlopen(req: request.Request, timeout: float):
        raise urllib_error.URLError("Connection refused")

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    result = CliRunner().invoke(cli, ["models"])
    assert result.exit_code != 0
    assert "Ollama request failed" in result.output


def test_models_command_uses_base_url_flag(monkeypatch):
    captured: dict[str, str] = {}

    class DummyResponse:
        def read(self) -> bytes:
            return json.dumps({"models": []}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req: request.Request, timeout: float):
        captured["url"] = req.full_url
        return DummyResponse()

    monkeypatch.setattr("modelable.llm.providers.request.urlopen", fake_urlopen)
    result = CliRunner().invoke(cli, ["models", "--base-url", "http://example.internal:11434"])
    assert result.exit_code == 0, result.output
    assert captured["url"] == "http://example.internal:11434/api/tags"
    assert "http://example.internal:11434" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_llm_provider_integration.py -k models_command -v`
Expected: FAIL — `models` is not a registered command (Click reports "No such command 'models'").

- [ ] **Step 3: Implement the command**

In `cli/src/modelable/commands/llm.py`, change the import line:

```python
from modelable.llm.providers import build_provider
```
to:
```python
from modelable.llm.providers import build_provider, list_ollama_models
```

Add `cli_group.add_command(models)` inside `register_llm_commands`, after
the existing `cli_group.add_command(chat)` line:

```python
def register_llm_commands(cli_group: click.Group) -> None:
    cli_group.add_command(describe)
    cli_group.add_command(generate)
    cli_group.add_command(import_model)
    cli_group.add_command(diff)
    cli_group.add_command(update)
    cli_group.add_command(attach)
    cli_group.add_command(transform)
    cli_group.add_command(suggest_projection_cmd)
    cli_group.add_command(ask)
    cli_group.add_command(recommend)
    cli_group.add_command(explain)
    cli_group.add_command(chat)
    cli_group.add_command(models)
```

Add the command itself anywhere after `register_llm_commands` (e.g. directly
below the `describe` command definition, to keep discovery-related commands
near the top of the file):

```python
@click.command()
@click.option("--base-url", "base_url", default=None, help="Ollama server base URL.")
def models(base_url: str | None) -> None:
    """List models installed on a local Ollama server."""
    config = resolve_llm_config(flag_base_url=base_url)
    resolved_base_url = config.base_url or "http://localhost:11434"
    try:
        model_names = list_ollama_models(resolved_base_url)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    if not model_names:
        console.print(f"No models installed on {resolved_base_url}. Run 'ollama pull <model>' to install one.")
        return
    for name in model_names:
        console.print(name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_llm_provider_integration.py -k models_command -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run ruff, mypy, and the full test file**

Run:
```bash
cd cli
uv run ruff format src/modelable/commands/llm.py tests/test_llm_provider_integration.py
uv run ruff check src/modelable/commands/llm.py tests/test_llm_provider_integration.py
uv run mypy src/modelable/commands/llm.py
uv run pytest tests/test_llm_provider_integration.py -v
```
Expected: ruff and mypy report no new issues, all tests pass (44 total in
this file after Tasks 1 and 2).

- [ ] **Step 6: Manual smoke test against the real local Ollama server**

The user confirmed Ollama is running locally. Run:
```bash
cd cli
uv run modelable models
```
Expected: prints the actual installed model names (or the "No models
installed" hint if none are pulled), exits 0. This confirms the command
works end-to-end against a real server, not just mocks.

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/commands/llm.py cli/tests/test_llm_provider_integration.py
git commit -m "feat(cli): add 'modelable models' command to list installed Ollama models"
```

---

### Task 3: Opt-in real-server conformance test

**Files:**
- Modify: `cli/tests/test_ollama_conversation_conformance.py`

**Interfaces:**
- Consumes: `list_ollama_models(base_url: str, timeout: float = 10.0) ->
  list[str]` from Task 1.

- [ ] **Step 1: Add the test**

This file already gates all its tests behind `MODELABLE_OLLAMA_TESTS=1` via
the module-level `pytestmark = pytest.mark.ollama` and the `_provider()`
helper's `pytest.skip(...)` check (see the file header, already read during
planning — `_provider()` skips unless `MODELABLE_OLLAMA_TESTS=1` is set and
`MODELABLE_OLLAMA_MODEL` is present). Add this test near the top of the file,
after the imports and before the existing conformance tests:

```python
def test_list_ollama_models_includes_conformance_model():
    if os.environ.get("MODELABLE_OLLAMA_TESTS") != "1":
        pytest.skip("set MODELABLE_OLLAMA_TESTS=1 to run local Ollama conformance")
    model = os.environ.get("MODELABLE_OLLAMA_MODEL")
    if not model:
        pytest.fail("MODELABLE_OLLAMA_MODEL is required when Ollama conformance is enabled")
    base_url = os.environ.get("MODELABLE_LLM_BASE_URL", "http://127.0.0.1:11434")
    names = list_ollama_models(base_url)
    assert model in names
```

Add `list_ollama_models` to this file's existing import line:
```python
from modelable.llm.providers import OllamaProvider
```
becomes:
```python
from modelable.llm.providers import OllamaProvider, list_ollama_models
```

- [ ] **Step 2: Run it against the real local Ollama server**

The user confirmed Ollama is running on this machine. Pick one of its
already-installed models (from the Task 2 Step 6 smoke test output) and run:

```bash
cd cli
MODELABLE_OLLAMA_TESTS=1 MODELABLE_OLLAMA_MODEL=<a model name from the smoke test output> uv run pytest tests/test_ollama_conversation_conformance.py -k list_ollama_models -v -n 0
```
Expected: PASS. (`-n 0` disables `pytest-xdist` parallelization for this
single real-network test, matching the pattern documented in
`docs/maintainers.md` for other Ollama conformance runs.)

- [ ] **Step 3: Confirm the test skips cleanly without the env vars**

Run: `cd cli && uv run pytest tests/test_ollama_conversation_conformance.py -k list_ollama_models -v`
Expected: SKIPPED (not run, not failed) — confirms this doesn't break the
default `pytest` run for contributors without a local Ollama server.

- [ ] **Step 4: Run ruff and mypy on the modified test file**

Run:
```bash
cd cli
uv run ruff format tests/test_ollama_conversation_conformance.py
uv run ruff check tests/test_ollama_conversation_conformance.py
uv run mypy tests/test_ollama_conversation_conformance.py
```
Expected: no new issues.

- [ ] **Step 5: Commit**

```bash
git add cli/tests/test_ollama_conversation_conformance.py
git commit -m "test(llm): add opt-in conformance check for list_ollama_models"
```

---

### Task 4: Full suite verification and docs update

**Files:**
- Modify: `docs/cli-reference.md` (document the new command)

**Interfaces:**
- None (documentation + verification only).

- [ ] **Step 1: Document the command**

In `docs/cli-reference.md`, find section 10 (the LLM-related commands —
10.3 `suggest-projection`, 10.4 `update`, 10.5 `chat`, per the numbering
already read during planning). Add a new subsection after 10.5 `chat`,
numbered 10.6:

```markdown
### 10.6 `models` — List installed Ollama models

```text
modelable models [--base-url URL]
```

Lists the models installed on a local Ollama server, so a model name is
known before passing `--provider ollama --model <name>` to `chat`, `update`,
or `docs-ask`. `--base-url` resolves the same way as the other LLM commands:
flag, then `MODELABLE_LLM_BASE_URL`, then `OLLAMA_HOST`, then
`http://localhost:11434`.

If no models are installed, prints a hint to run `ollama pull <model>`. If
the Ollama server is unreachable, exits with an error describing the
connection failure.
```

Note: unlike `update`/`chat`/`suggest-projection`, `models` is a read-only
query — it doesn't call a provider for generation and writes no provenance
sidecar, so it doesn't fall under the "AI-Assisted Authoring" provenance
contract in section 12. Don't add a "Defined in: section 12" footer to this
subsection.

- [ ] **Step 2: Run the full CLI test suite**

Run: `cd cli && uv run pytest -q`
Expected: all tests pass (the two Ollama-gated tests added in Task 3 show as
skipped unless `MODELABLE_OLLAMA_TESTS=1` is set).

- [ ] **Step 3: Run full ruff and mypy checks**

Run:
```bash
cd cli
uv run ruff format --check .
uv run ruff check .
uv run mypy .
```
Expected: no new issues beyond the project's existing mypy baseline (per
this project's pre-commit convention — compare against the baseline file if
`mypy` reports pre-existing errors unrelated to these changes).

- [ ] **Step 4: Commit**

```bash
git add docs/cli-reference.md
git commit -m "docs(cli): document 'modelable models' command"
```

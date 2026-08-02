# Ollama Model Discovery — Design

**Date:** 2026-08-02

## Status

Proposed. First of two planned sub-projects toward "local-LLM model discovery":

- **A (this design):** CLI model discovery for the existing Ollama provider.
- **B (future):** Playground Ollama provider, per
  [ROADMAP.md](../../../ROADMAP.md) item 10 ("Active next phase:
  extensibility ... optional local Ollama provider"). Deferred because it
  needs a different architecture (async browser fetch to `localhost:11434`
  with CORS, a provider-selection UI, and integration with the WebLLM-based
  async LLM bridge from
  [Playground Local AI — Design](archived/2026-07-22-playground-local-ai-design.md))
  and is naturally sequenced after A.

## Context

The CLI already supports Ollama as an LLM provider
(`cli/src/modelable/llm/providers.py`): `--provider ollama --model <name>
[--base-url URL]` on `chat`, `update`, and `docs-ask`. `build_provider`
requires a model name up front and has no way to tell the user what's
actually installed on their Ollama server — they must already know the exact
tag (e.g. `llama3.2` vs `llama3.2:1b`) or the command fails with `ollama
provider requires a model`.

There is no discovery mechanism: no command lists what models a local Ollama
server has pulled.

## Goals

- Let a user list the models installed on their local Ollama server from the
  CLI.
- Keep the existing `--provider ollama` behavior unchanged: a model is still
  required explicitly (via `--model`, `MODELABLE_LLM_MODEL`, or workspace
  `ai.model`); discovery does not introduce any auto-selection or fallback.

## Non-goals

- Any other local backend (LM Studio, llama.cpp server, vLLM, etc.) or a
  generic OpenAI-compatible-local-server abstraction. Scope is Ollama only.
- Auto-selecting or defaulting a model when one isn't specified, even if only
  one is installed. `build_provider` keeps requiring an explicit model.
- Playground/web UI changes (sub-project B, above).
- Streaming, interactive model pickers, or any change to `resolve_llm_config`.

## Architecture

Add one function next to `OllamaProvider` in
`cli/src/modelable/llm/providers.py`:

```python
def list_ollama_models(base_url: str, timeout: float = 10.0) -> list[str]:
    ...
```

It issues `GET {base_url}/api/tags`, parses the JSON response's
`models[].name` array, and returns the names sorted alphabetically. It reuses
the same `error.HTTPError` / `error.URLError` → `RuntimeError` translation
already used by `OllamaProvider._post_json` and `AnthropicProvider._post_json`,
so failure messages are consistent with the rest of the module (e.g.
`"Ollama request failed: <reason>"`). `urllib.request` is used directly (GET,
no body), matching the existing dependency-free transport style in this file.

## Components

### `list_ollama_models` (providers.py)

- Input: `base_url` (same resolution as other Ollama calls — caller passes
  `resolve_llm_config(...).base_url`), optional `timeout`.
- Output: `list[str]` of installed model tags, alphabetically sorted.
- Errors: raises `RuntimeError` on connection failure or invalid JSON, same
  pattern as `_post_json`.

### `modelable models` command (commands/llm.py)

New Click command registered in `register_llm_commands`, alongside `chat`,
`update`, etc. All commands registered by `register_llm_commands` are
top-level (`cli_group.add_command(...)` with no subgroup), so this follows
the same flat naming as `describe`, `ask`, `chat`:

```text
modelable models [--base-url URL]
```

- `--base-url` resolves the same way other commands resolve it: flag →
  `MODELABLE_LLM_BASE_URL` → `OLLAMA_HOST` → `http://localhost:11434` (via
  `resolve_llm_config`, called with no provider/model so only `base_url`
  resolution matters).
- On success with models installed: prints one model name per line.
- On success with zero models: prints a hint, e.g. `No models installed.
  Run 'ollama pull <model>' to install one.`
- On connection failure: raises `click.ClickException` wrapping the
  `RuntimeError` message (consistent with how `update`/`chat` surface
  provider errors today).

## Testing

- Unit tests in `cli/tests/test_llm_provider_integration.py` (mocking
  `urllib.request.urlopen`, following that file's existing style):
  - `list_ollama_models` parses a multi-model `/api/tags` response correctly
    and returns sorted names.
  - `list_ollama_models` returns `[]` for an empty `models` array.
  - `list_ollama_models` raises `RuntimeError` on connection failure
    (`URLError`) and on HTTP error (`HTTPError`).
  - `modelable models` CLI command (via `CliRunner`) prints model names
    on success, prints the no-models hint on an empty list, and exits with a
    `ClickException` message on connection failure.
- One real-server smoke test added to
  `cli/tests/test_ollama_conversation_conformance.py`, gated the same way as
  the rest of that file (`MODELABLE_OLLAMA_TESTS=1`,
  `MODELABLE_OLLAMA_MODEL` present in the returned list).
- Full existing suite (`uv run pytest`) plus `ruff format --check`, `ruff
  check`, and the mypy baseline ratchet must still pass, per this project's
  pre-commit convention.

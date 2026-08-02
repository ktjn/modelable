# Ship Bundled Documentation Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Modelable documentation search index inside the `modelable` Python wheel and use it as the default for CLI chat, `docs-ask`, and LSP/VSCode chat `/docs` retrieval.

**Architecture:** A Hatchling custom build hook generates `src/modelable/data/docs-index/` from `docs/` during wheel/sdist builds. A runtime helper discovers the shipped manifest via `importlib.resources`. CLI chat, `docs-ask`, and LSP chat default to the bundled index while still allowing `--docs-index` / `documentationIndexUri` overrides.

**Tech Stack:** Python 3.14, Hatchling, `searchable-indexer`, `searchable-client`, `importlib.resources`, `click`, `pytest`.

## Global Constraints

- Python version: `>=3.14`.
- Bundled index format: lexical JSON Searchable index, matching the current `docs-index` command defaults.
- Existing `dist/search-index/` at the repository root must remain unchanged.
- User-provided indexes via `--docs-index` or `documentationIndexUri` take precedence over the bundled index.
- LSP workspace-root containment validation applies only to user-supplied URIs, not the bundled package index.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `cli/src/modelable/rag/bundled_index_builder.py` | Shared logic to build the bundled index from a docs root into an output directory. |
| `cli/src/modelable/rag/bundled_index.py` | Runtime helper that returns the path to the shipped `manifest.json` via `importlib.resources`. |
| `cli/src/modelable/data/__init__.py` | Makes `modelable.data` a package so `importlib.resources.files("modelable.data")` resolves. |
| `cli/scripts/build_bundled_docs_index.py` | Dev script that generates `src/modelable/data/docs-index/` for local development and tests. |
| `cli/hatch_build.py` | Hatchling custom build hook that invokes the builder during wheel/sdist builds. |
| `cli/pyproject.toml` | Adds `searchable-indexer` to `[build-system] requires` and registers the custom build hook. |
| `cli/src/modelable/commands/llm.py` | CLI chat command defaults to bundled index when `--docs-index` is omitted. |
| `cli/src/modelable/commands/docs_ask.py` | `docs-ask` changes to `docs-ask QUESTION [--docs-index PATH]` and defaults to bundled index. |
| `cli/src/modelable/lsp/conversation_service.py` | LSP chat defaults to bundled index when `documentation_index_uri` is `None`. |
| `docs/cli-reference.md` | Updates `docs-ask` and `chat` examples to reflect the optional index. |

---

### Task 1: Add bundled index builder module

**Files:**
- Create: `cli/src/modelable/rag/bundled_index_builder.py`
- Test: `cli/tests/test_rag_bundled_index_builder.py`

**Interfaces:**
- Produces: `build_bundled_index(docs_root: Path, output_dir: Path, *, base_url: str = "https://ktjn.github.io/modelable/") -> Path` returning the generated `manifest.json` path.

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from modelable.rag.bundled_index_builder import build_bundled_index


def test_build_bundled_index_creates_manifest_and_docs(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "guide.md").write_text("# Guide\n\nInstall with uv.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    manifest_path = build_bundled_index(docs_root, output_dir)

    assert manifest_path == output_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_file = output_dir / manifest["shards"]["docs"][0]["file"]
    docs = json.loads(doc_file.read_text(encoding="utf-8"))
    assert "1" in docs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rag_bundled_index_builder.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'modelable.rag.bundled_index_builder'`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
from pathlib import Path

from modelable.rag.chunking import load_documentation_chunks
from modelable.rag.index import build_documentation_index


def build_bundled_index(
    docs_root: Path,
    output_dir: Path,
    *,
    base_url: str = "https://ktjn.github.io/modelable/",
) -> Path:
    """Generate a Searchable documentation index from docs_root into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_documentation_chunks(docs_root, base_url=base_url)
    build_documentation_index(chunks, output_dir)
    return output_dir / "manifest.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rag_bundled_index_builder.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/rag/bundled_index_builder.py cli/tests/test_rag_bundled_index_builder.py
git commit -m "feat(rag): add bundled documentation index builder"
```

---

### Task 2: Add runtime helper for the shipped index

**Files:**
- Create: `cli/src/modelable/rag/bundled_index.py`
- Create: `cli/src/modelable/data/__init__.py`
- Test: `cli/tests/test_rag_bundled_index.py`

**Interfaces:**
- Produces: `bundled_documentation_index_path() -> Path` raising `RuntimeError` when the shipped index is missing.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from modelable.rag.bundled_index import bundled_documentation_index_path


def test_bundled_documentation_index_path_returns_manifest(monkeypatch, tmp_path: Path) -> None:
    fake_data = tmp_path / "modelable" / "data"
    fake_docs_index = fake_data / "docs-index"
    fake_docs_index.mkdir(parents=True)
    manifest = fake_docs_index / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "modelable.rag.bundled_index.importlib.resources.files",
        lambda package: fake_data if package == "modelable.data" else tmp_path,
    )

    assert bundled_documentation_index_path() == manifest


def test_bundled_documentation_index_path_raises_when_missing(monkeypatch, tmp_path: Path) -> None:
    fake_data = tmp_path / "modelable" / "data"
    fake_data.mkdir(parents=True)

    monkeypatch.setattr(
        "modelable.rag.bundled_index.importlib.resources.files",
        lambda package: fake_data if package == "modelable.data" else tmp_path,
    )

    with pytest.raises(RuntimeError, match="Bundled documentation index"):
        bundled_documentation_index_path()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rag_bundled_index.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# cli/src/modelable/rag/bundled_index.py
from __future__ import annotations

import importlib.resources
from pathlib import Path


def bundled_documentation_index_path() -> Path:
    """Return the path to the documentation index shipped with the package."""
    manifest = importlib.resources.files("modelable.data") / "docs-index" / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(
            "Bundled documentation index is missing. "
            "Install a Modelable wheel or run scripts/build_bundled_docs_index.py."
        )
    return Path(str(manifest))
```

```python
# cli/src/modelable/data/__init__.py
"""Package data directory."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rag_bundled_index.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/rag/bundled_index.py cli/src/modelable/data/__init__.py cli/tests/test_rag_bundled_index.py
git commit -m "feat(rag): add runtime helper for bundled documentation index"
```

---

### Task 3: Add dev script to generate the bundled index

**Files:**
- Create: `cli/scripts/build_bundled_docs_index.py`
- Test: `cli/tests/test_build_bundled_docs_index_script.py`

**Interfaces:**
- Consumes: `build_bundled_index` from Task 1.
- Produces: Populates `cli/src/modelable/data/docs-index/` from `docs/`.

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
from pathlib import Path


def test_dev_script_generates_manifest(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "guide.md").write_text("# Guide\n\nInstall with uv.\n", encoding="utf-8")
    output_dir = tmp_path / "data" / "docs-index"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_bundled_docs_index.py",
            "--docs-root",
            str(docs_root),
            "--out",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "manifest.json").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_bundled_docs_index_script.py -v`

Expected: FAIL with `FileNotFoundError` because the script does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import argparse
from pathlib import Path

from modelable.rag.bundled_index_builder import build_bundled_index


CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
DOCS_ROOT = REPO_ROOT / "docs"
OUTPUT_DIR = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"


def _docs_root() -> Path:
    return DOCS_ROOT


def _output_dir() -> Path:
    return OUTPUT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled documentation index for development")
    parser.add_argument("--docs-root", type=Path, default=_docs_root())
    parser.add_argument("--out", type=Path, default=_output_dir())
    args = parser.parse_args()

    if not args.docs_root.is_dir():
        raise SystemExit(f"Documentation root does not exist: {args.docs_root}")

    build_bundled_index(args.docs_root, args.out)
    print(f"Bundled documentation index written to {args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_bundled_docs_index_script.py -v`

Expected: PASS.

- [ ] **Step 5: Generate the initial bundled index for development**

Run: `uv run python scripts/build_bundled_docs_index.py`

Expected: `cli/src/modelable/data/docs-index/manifest.json` and shard files are created.

- [ ] **Step 6: Commit**

```bash
git add cli/scripts/build_bundled_docs_index.py cli/tests/test_build_bundled_docs_index_script.py cli/src/modelable/data/docs-index
git commit -m "feat(rag): add dev script to build bundled documentation index"
```

---

### Task 4: Add Hatchling build hook

**Files:**
- Create: `cli/hatch_build.py`
- Modify: `cli/pyproject.toml` (`[build-system]` and add `[tool.hatch.build.hooks.custom]`)
- Test: Build a wheel and inspect contents.

**Interfaces:**
- Consumes: `build_bundled_index` from Task 1.
- Produces: `src/modelable/data/docs-index/` inside the wheel.

- [ ] **Step 1: Write the build hook**

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

CLI_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CLI_ROOT.parent


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        sys.path.insert(0, str(CLI_ROOT / "src"))
        from modelable.rag.bundled_index_builder import build_bundled_index

        docs_root = REPO_ROOT / "docs"
        if not docs_root.is_dir():
            # When building from an sdist, docs are included at the repository root.
            docs_root = Path("docs").resolve()
        if not docs_root.is_dir():
            raise RuntimeError(f"Documentation root not found: {docs_root}")

        output_dir = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"
        build_bundled_index(docs_root, output_dir)
```

- [ ] **Step 2: Register the hook in pyproject.toml**

Modify `cli/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling", "searchable-indexer>=0.1.1"]
build-backend = "hatchling.build"
```

Add at the end:

```toml
[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
```

- [ ] **Step 3: Verify the wheel contains the bundled index**

Run:

```bash
uv build --wheel --out-dir tmp_dist
unzip -l tmp_dist/*.whl | grep "docs-index"
```

Expected: `modelable/data/docs-index/manifest.json` and shard files are listed.

- [ ] **Step 4: Commit**

```bash
git add cli/hatch_build.py cli/pyproject.toml
git commit -m "feat(build): generate bundled documentation index during wheel build"
```

---

### Task 5: Wire CLI chat default to bundled index

**Files:**
- Modify: `cli/src/modelable/commands/llm.py` around the `chat` command
- Test: `cli/tests/test_cli_docs_ask.py` (add CLI chat default test)

**Interfaces:**
- Consumes: `bundled_documentation_index_path()` from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_cli_docs_ask.py`:

```python
def test_llm_chat_docs_uses_bundled_index_by_default(tmp_path: Path, monkeypatch) -> None:
    bundled = tmp_path / "bundled" / "manifest.json"
    bundled.parent.mkdir(parents=True)
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="Install with uv.",
                chunk_index=0,
            )
        ],
        bundled.parent,
    )
    monkeypatch.setattr("modelable.commands.llm.bundled_documentation_index_path", lambda: bundled)
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "/docs install",
            "--provider",
            "fake",
            "--model",
            "test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Use [S1] to install it." in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_docs_ask.py::test_llm_chat_docs_uses_bundled_index_by_default -v`

Expected: FAIL because `modelable.commands.llm.bundled_documentation_index_path` does not exist.

- [ ] **Step 3: Modify CLI chat command**

In `cli/src/modelable/commands/llm.py`, import the helper and update the retriever construction:

```python
from modelable.rag.bundled_index import bundled_documentation_index_path
```

Change:

```python
documentation_retriever = DocumentationRetriever(docs_index) if docs_index is not None else None
```

to:

```python
if docs_index is not None:
    documentation_retriever = DocumentationRetriever(docs_index)
else:
    documentation_retriever = DocumentationRetriever(bundled_documentation_index_path())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_docs_ask.py::test_llm_chat_docs_uses_bundled_index_by_default -v`

Expected: PASS.

- [ ] **Step 5: Update existing test expectations**

The test `test_llm_chat_docs_requires_docs_index_for_one_shot_docs_question` now expects bundled index behavior. Update it to assert that `/docs install` returns an answer when the bundled index is present, or monkeypatch the helper to raise so it still tests the missing-index path. For now, monkeypatch to raise and keep the existing assertion:

```python
def test_llm_chat_docs_requires_docs_index_for_one_shot_docs_question(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "modelable.commands.llm.bundled_documentation_index_path",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--message",
            "/docs how do I install it?",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "--docs-index" in result.output
```

- [ ] **Step 6: Run all docs-ask/chat tests**

Run: `uv run pytest tests/test_cli_docs_ask.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/commands/llm.py cli/tests/test_cli_docs_ask.py
git commit -m "feat(cli): default chat /docs to bundled documentation index"
```

---

### Task 6: Wire docs-ask default to bundled index

**Files:**
- Modify: `cli/src/modelable/commands/docs_ask.py`
- Test: `cli/tests/test_cli_docs_ask.py`

**Interfaces:**
- Consumes: `bundled_documentation_index_path()` from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_cli_docs_ask.py`:

```python
def test_docs_ask_uses_bundled_index_by_default(tmp_path: Path, monkeypatch) -> None:
    bundled = tmp_path / "bundled" / "manifest.json"
    bundled.parent.mkdir(parents=True)
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="Install with uv.",
                chunk_index=0,
            )
        ],
        bundled.parent,
    )
    monkeypatch.setattr("modelable.commands.docs_ask.bundled_documentation_index_path", lambda: bundled)
    monkeypatch.setattr("modelable.commands.docs_ask.build_provider", lambda *args, **kwargs: FakeProvider())

    result = CliRunner().invoke(cli, ["docs-ask", "install", "--provider", "fake", "--model", "test"])

    assert result.exit_code == 0, result.output
    assert "Use [S1] to install it." in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_docs_ask.py::test_docs_ask_uses_bundled_index_by_default -v`

Expected: FAIL because `docs-ask` still requires two positional arguments.

- [ ] **Step 3: Modify docs_ask command signature**

In `cli/src/modelable/commands/docs_ask.py`:

```python
from modelable.rag.bundled_index import bundled_documentation_index_path


@click.command("docs-ask")
@click.argument("question")
@click.option(
    "--docs-index",
    "docs_index",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional documentation search index manifest; defaults to the bundled index.",
)
```

And change the function body to use the bundled index when `docs_index` is `None`:

```python
def docs_ask(
    question: str,
    docs_index: Path | None,
    limit: int,
    max_context_words: int,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    as_json: bool,
) -> None:
    """Answer QUESTION using evidence retrieved from the documentation index."""
    try:
        index = docs_index if docs_index is not None else bundled_documentation_index_path()
        config = resolve_llm_config(...)
        llm_provider = build_provider(...)
        result = answer_with_retrieval(
            DocumentationRetriever(index),
            ...
        )
```

- [ ] **Step 4: Update existing docs-ask tests**

Change existing invocations from `docs-ask [str(index)] "install"` to `docs-ask "install" --docs-index [str(index)]`.

- [ ] **Step 5: Run all docs-ask tests**

Run: `uv run pytest tests/test_cli_docs_ask.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/commands/docs_ask.py cli/tests/test_cli_docs_ask.py
git commit -m "feat(cli): default docs-ask to bundled documentation index"
```

---

### Task 7: Wire LSP chat default to bundled index

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Test: `cli/tests/test_lsp_conversation_service.py`

**Interfaces:**
- Consumes: `bundled_documentation_index_path()` from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_lsp_conversation_service.py`:

```python
def test_lsp_docs_uses_bundled_index_by_default(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    bundled = tmp_path / "bundled" / "manifest.json"
    bundled.parent.mkdir(parents=True)
    build_documentation_index(
        [
            DocumentationChunk(
                external_id="guide.md#install",
                source_path="guide.md",
                url="https://example.test/guide/#install",
                language="en",
                title="Guide",
                heading="Install",
                heading_path=["Guide", "Install"],
                content="How do I configure install? Install with uv.",
                chunk_index=0,
            )
        ],
        bundled.parent,
    )
    monkeypatch.setattr(
        "modelable.lsp.conversation_service.bundled_documentation_index_path",
        lambda: bundled,
    )

    class DocsProvider:
        def complete(self, request: object) -> LLMResponse:
            return LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.provider = DocsProvider()
            self.no_provider_notice = None
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(root)
            self.messages: list[str] = []

        def turn(self, message: str) -> ConversationReply:
            self.messages.append(message)
            return ConversationReply(kind="answer", text="planner answer", focused_ref=self.focused_ref)

        def close(self) -> None:
            return None

    def session_factory(root: Path, focused_ref: str | None):
        return RecordingSession(root=root, focused_ref=focused_ref)

    service = LspConversationService(session_factory=session_factory)
    reply = service.turn(
        _turn_params(root, create_session=True).model_copy(update={"message": "/docs install"})
    )

    assert reply["kind"] == "answer"
    assert reply["retrievalUsed"] is True
    assert "Use [S1] to install it." in reply["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lsp_conversation_service.py::test_lsp_docs_uses_bundled_index_by_default -v`

Expected: FAIL because the service returns missing-index guidance.

- [ ] **Step 3: Modify LSP conversation service**

In `cli/src/modelable/lsp/conversation_service.py`:

```python
from modelable.rag.bundled_index import bundled_documentation_index_path
```

Update `_create_documentation_retriever`:

```python
def _create_documentation_retriever(
    self,
    root: Path,
    documentation_index_uri: str | None,
) -> tuple[str | None, DocumentationRetriever | None]:
    if documentation_index_uri is None:
        resolved = bundled_documentation_index_path()
        try:
            retriever = DocumentationRetriever(resolved)
        except Exception as error:
            raise ConversationSessionError(
                f"Could not load the bundled documentation index: {error}"
            ) from error
        return resolved.as_uri(), retriever

    resolved = self._resolve_documentation_index_path(root, documentation_index_uri)
    try:
        manifest = json.loads(resolved.read_bytes())
        self._validate_documentation_shard_paths(root, resolved, manifest)
        retriever = DocumentationRetriever(resolved)
    except ConversationSessionError:
        raise
    except Exception as error:
        raise ConversationSessionError(
            f"Could not load the documentation index from {resolved}: {error}"
        ) from error
    return resolved.as_uri(), retriever
```

- [ ] **Step 4: Run the new test**

Run: `uv run pytest tests/test_lsp_conversation_service.py::test_lsp_docs_uses_bundled_index_by_default -v`

Expected: PASS.

- [ ] **Step 5: Update existing missing-index test**

`test_lsp_docs_without_index_returns_missing_index_guidance_without_provider_notice` should now monkeypatch the bundled helper to raise so it still tests the no-index path:

```python
def test_lsp_docs_without_index_returns_missing_index_guidance_without_provider_notice(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    monkeypatch.setattr(
        "modelable.lsp.conversation_service.bundled_documentation_index_path",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    service = LspConversationService(session_factory=_session_factory)
    reply = service.turn(_turn_params(root, create_session=True).model_copy(update={"message": "/docs install"}))

    assert reply["kind"] == "answer"
    assert reply["text"] == "The /docs command requires --docs-index to be configured."
```

- [ ] **Step 6: Run all LSP conversation service tests**

Run: `uv run pytest tests/test_lsp_conversation_service.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/lsp/conversation_service.py cli/tests/test_lsp_conversation_service.py
git commit -m "feat(lsp): default /docs to bundled documentation index"
```

---

### Task 8: Update CLI reference documentation

**Files:**
- Modify: `docs/cli-reference.md`

- [ ] **Step 1: Update `docs-ask` section**

Find the `docs-ask` section and change:

```markdown
### 5.6.2 `docs-ask` — Answer a question from the documentation index

```text
modelable docs-ask INDEX QUESTION [--limit N] [--max-context-words N] \
  [--provider NAME] [--model MODEL] [--base-url URL] [--json]
```
```

to:

```markdown
### 5.6.2 `docs-ask` — Answer a question from the documentation index

```text
modelable docs-ask QUESTION [--docs-index PATH] [--limit N] [--max-context-words N] \
  [--provider NAME] [--model MODEL] [--base-url URL] [--json]
```
```

And update the examples to use `--docs-index`.

- [ ] **Step 2: Update `chat` section**

Change the `--docs-index` help text from "Optional documentation search index manifest for `/docs` questions" to "Optional documentation search index manifest; defaults to the bundled index." Update the example to show that `--docs-index` is now optional.

- [ ] **Step 3: Commit**

```bash
git add docs/cli-reference.md
git commit -m "docs(cli): document bundled documentation index defaults"
```

---

## Self-Review

### Spec coverage

- Build-time generation: Task 1 (builder), Task 3 (dev script), Task 4 (Hatchling hook).
- Runtime helper: Task 2.
- CLI chat default: Task 5.
- `docs-ask` default: Task 6.
- LSP default: Task 7.
- Override preserved: All tasks keep `--docs-index` / `documentation_index_uri` precedence.
- Docs update: Task 8.

### Placeholder scan

No TBD, TODO, or vague steps. Each step includes concrete code or commands.

### Type consistency

- `build_bundled_index(docs_root: Path, output_dir: Path, *, base_url: str = "...") -> Path` is used consistently across the builder, script, and hook.
- `bundled_documentation_index_path() -> Path` is imported from `modelable.rag.bundled_index` in all callers.

---

## Verification

After all tasks, run the standard pre-commit checks from `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

All must pass before pushing.

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.llm.provider_types import LLMResponse
from modelable.rag.index import build_documentation_index
from modelable.rag.model import DocumentationChunk


class FakeProvider:
    def complete(self, request: object) -> LLMResponse:
        return LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")


class FailingProvider:
    def complete(self, request: object) -> LLMResponse:
        raise RuntimeError("documentation provider unavailable")


def make_index(tmp_path: Path, *, content: str) -> Path:
    index = tmp_path / "index"
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
                content=content,
                chunk_index=0,
            )
        ],
        index,
    )
    return index / "manifest.json"


def test_docs_ask_prints_answer_and_sources(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    monkeypatch.setattr("modelable.commands.docs_ask.build_provider", lambda *args, **kwargs: FakeProvider())

    result = CliRunner().invoke(
        cli,
        ["docs-ask", str(index), "install", "--provider", "fake", "--model", "test"],
    )

    assert result.exit_code == 0, result.output
    assert "Use [S1] to install it." in result.output
    assert "guide.md#install" in result.output
    assert "https://example.test/guide/#install" in result.output


def test_docs_ask_json_keeps_structured_citations(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    monkeypatch.setattr("modelable.commands.docs_ask.build_provider", lambda *args, **kwargs: FakeProvider())

    result = CliRunner().invoke(
        cli,
        ["docs-ask", str(index), "install", "--provider", "fake", "--model", "test", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["insufficient_evidence"] is False
    assert payload["citations"][0]["label"] == "S1"
    assert payload["citations"][0]["external_id"] == "guide.md#install"


def test_docs_ask_returns_insufficient_evidence_for_empty_index(tmp_path: Path) -> None:
    index = tmp_path / "index"
    build_documentation_index([], index)

    result = CliRunner().invoke(
        cli, ["docs-ask", str(index / "manifest.json"), "Unknown question", "--provider", "local"]
    )

    assert result.exit_code == 0, result.output
    assert "enough documentation evidence" in result.output


def test_llm_chat_docs_uses_docs_index_for_one_shot_docs_question(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FakeProvider())

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--docs-index",
            str(index),
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
    assert "guide.md#install" in result.output
    assert "https://example.test/guide/#install" in result.output


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


def test_llm_chat_docs_missing_provider_with_evidence_returns_configuration_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: None)

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--docs-index",
            str(index),
            "--message",
            "/docs install",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Documentation answers with evidence require an LLM provider" in result.output
    assert "--provider/--model" in result.output
    assert "workspace/environment configuration" in result.output


def test_llm_chat_docs_one_shot_renders_provider_failure(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FailingProvider())

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--docs-index",
            str(index),
            "--message",
            "/docs install",
            "--provider",
            "fake",
            "--model",
            "test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "The configured provider failed during the documentation answer request:" in result.output
    assert "documentation provider unavailable" in result.output


def test_llm_chat_docs_interactive_session_continues_after_provider_failure(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")
    monkeypatch.setattr("modelable.commands.llm.build_provider", lambda *args, **kwargs: FailingProvider())

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--docs-index",
            str(index),
            "--provider",
            "fake",
            "--model",
            "test",
        ],
        input="/docs install\n/help\n/exit\n",
    )

    assert result.exit_code == 0, result.output
    assert "documentation provider unavailable" in result.output
    assert "assistant> Commands:" in result.output


def test_llm_chat_docs_keeps_ordinary_one_shot_messages_on_conversation_session(tmp_path: Path, monkeypatch) -> None:
    index = make_index(tmp_path, content="Install with uv.")
    workspace = tmp_path / "workspace.mdl"
    workspace.write_text('domain customer {\n  owner: "docs-team"\n}\n', encoding="utf-8")

    class RecordingSession:
        def __init__(self, **kwargs) -> None:
            self.no_provider_notice = None
            self.messages: list[str] = []
            self.focused_ref = kwargs.get("focused_ref")
            self.workspace = load_workspace(tmp_path)

        def turn(self, message: str):
            self.messages.append(message)
            return type("Reply", (), {"text": "session reply"})()

        def close(self) -> None:
            return None

    created: list[RecordingSession] = []

    def session_factory(**kwargs):
        session = RecordingSession(**kwargs)
        created.append(session)
        return session

    monkeypatch.setattr("modelable.commands.llm.ConversationSession", session_factory)

    result = CliRunner().invoke(
        cli,
        [
            "chat",
            "--path",
            str(tmp_path),
            "--docs-index",
            str(index),
            "--message",
            "hello there",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "session reply"
    assert len(created) == 1
    assert created[0].messages == ["hello there"]

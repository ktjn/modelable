import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.llm.provider_types import LLMResponse
from modelable.rag.index import build_documentation_index
from modelable.rag.model import DocumentationChunk


class FakeProvider:
    def complete(self, request: object) -> LLMResponse:
        return LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")


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

from pathlib import Path

import pytest

from modelable.rag.index import build_documentation_index
from modelable.rag.model import DocumentationChunk
from modelable.rag.retriever import DocumentationRetriever, RetrievedChunk


class FakeHit:
    def __init__(self) -> None:
        self.id = 17
        self.external_id = "guide.md#install"
        self.url = "https://example.test/guide/#install"
        self.score = 4.5
        self.fields = {
            "title": "Guide",
            "heading": "Install",
            "content": "Install with uv.",
            "source_path": "guide.md",
        }
        self.metadata = {"headingPath": ["Guide", "Install"], "chunkIndex": 0}
        self.content_hash = "hash-1"


class FakeResult:
    def __init__(self, hits: list[FakeHit] | None = None) -> None:
        self.hits = hits if hits is not None else [FakeHit()]


class FakeClient:
    def __init__(self) -> None:
        self.query: str | None = None
        self.options = None

    def search(self, query: str, options: object) -> FakeResult:
        self.query = query
        self.options = options
        return FakeResult()


def test_search_maps_searchable_hit_to_modelable_chunk() -> None:
    client = FakeClient()
    retriever = DocumentationRetriever("index/manifest.json", client=client)

    result = retriever.search("install", limit=5)

    assert result == [
        RetrievedChunk(
            id=17,
            external_id="guide.md#install",
            url="https://example.test/guide/#install",
            score=4.5,
            title="Guide",
            heading="Install",
            content="Install with uv.",
            source_path="guide.md",
            heading_path=["Guide", "Install"],
            content_hash="hash-1",
        )
    ]
    assert client.query == "install"
    assert client.options.limit == 5


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_blank_query(query: str) -> None:
    with pytest.raises(ValueError, match="query must not be blank"):
        DocumentationRetriever("index/manifest.json", client=FakeClient()).search(query)


@pytest.mark.parametrize("limit", [0, -1])
def test_search_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        DocumentationRetriever("index/manifest.json", client=FakeClient()).search("install", limit=limit)


def test_search_normalizes_natural_language_punctuation() -> None:
    client = FakeClient()

    DocumentationRetriever("index/manifest.json", client=client).search("domain ownership: how is it handled?")

    assert client.query == "domain ownership how is it handled"


def test_search_rejects_unsupported_mode() -> None:
    client = FakeClient()

    with pytest.raises(ValueError, match="unsupported search mode"):
        DocumentationRetriever("index/manifest.json", client=client).search("semantic", mode="bogus")  # type: ignore[arg-type]

    assert client.query is None


def test_search_rejects_missing_required_stored_field() -> None:
    client = FakeClient()
    client_hit = FakeHit()
    del client_hit.fields["content"]
    client.search = lambda query, options: FakeResult([client_hit])  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="missing stored field: content"):
        DocumentationRetriever("index/manifest.json", client=client).search("install")


def test_retriever_accepts_path_like_index_url() -> None:
    client = FakeClient()

    DocumentationRetriever(Path("index/manifest.json"), client=client)


def test_searches_real_json_index(tmp_path: Path) -> None:
    chunk = DocumentationChunk(
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
    index_directory = tmp_path / "index"
    build_documentation_index([chunk], index_directory)

    result = DocumentationRetriever(index_directory / "manifest.json").search("install")

    assert len(result) == 1
    assert result[0].external_id == "guide.md#install"
    assert result[0].content == "Install with uv."
    assert result[0].heading_path == ["Guide", "Install"]
    assert result[0].content_hash is not None

from __future__ import annotations

from dataclasses import dataclass

import pytest

import modelable.browser.rag as browser_rag
from modelable.browser.rag import (
    BrowserDocumentationRetriever,
    BrowserRetrievalError,
    RetrievedChunk,
    validate_index_url,
)
from modelable.rag.retriever import RetrievedChunk as SharedRetrievedChunk


def test_validate_index_url_accepts_same_origin_url_under_asset_root() -> None:
    assert (
        validate_index_url(
            "docs-index/manifest.json",
            "https://example.test/modelable/playground/",
        )
        == "https://example.test/modelable/playground/docs-index/manifest.json"
    )


@pytest.mark.parametrize(
    "index_url",
    [
        "https://other.test/modelable/playground/docs-index/manifest.json",
        "//other.test/modelable/playground/docs-index/manifest.json",
    ],
)
def test_validate_index_url_rejects_cross_origin_url(index_url: str) -> None:
    with pytest.raises(ValueError, match="same origin"):
        validate_index_url(index_url, "https://example.test/modelable/playground/")


def test_validate_index_url_rejects_parent_directory_escape() -> None:
    with pytest.raises(ValueError, match="asset root"):
        validate_index_url("../docs-index/manifest.json", "https://example.test/modelable/playground/")


def test_browser_rag_reuses_shared_retrieved_chunk_contract() -> None:
    assert RetrievedChunk is SharedRetrievedChunk


@dataclass(slots=True)
class FakeHit:
    id: int = 17
    external_id: str = "guide.md#install"
    url: str = "https://example.test/modelable/playground/guide/#install"
    score: float = 4.5
    fields: dict[str, str] = None  # type: ignore[assignment]
    metadata: dict[str, object] = None  # type: ignore[assignment]
    content_hash: str | None = "hash-1"

    def __post_init__(self) -> None:
        if self.fields is None:
            self.fields = {
                "title": "Guide",
                "heading": "Install",
                "content": "Install with uv.",
                "source_path": "guide.md",
            }
        if self.metadata is None:
            self.metadata = {"headingPath": ["Guide", "Install"], "chunkIndex": 0}


class FakeResult:
    def __init__(self, hits: list[FakeHit] | None = None) -> None:
        self.hits = hits if hits is not None else [FakeHit()]


def test_browser_documentation_retriever_maps_fake_search_client_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeSearchClient:
        def __init__(self, index_url: str, **kwargs: object) -> None:
            captured["index_url"] = index_url
            captured["kwargs"] = kwargs

        def search(self, query: str, options: object) -> FakeResult:
            captured["query"] = query
            captured["options"] = options
            return FakeResult()

    monkeypatch.setattr(browser_rag, "SearchClient", FakeSearchClient)

    retriever = BrowserDocumentationRetriever(
        "docs-index/manifest.json",
        "https://example.test/modelable/playground/",
    )
    result = retriever.search("install docs", limit=5)

    assert captured["index_url"] == "https://example.test/modelable/playground/docs-index/manifest.json"
    assert captured["kwargs"] == {"strict": True, "allow_cross_origin_shards": False}
    assert captured["query"] == "install docs"
    assert captured["options"].limit == 5
    assert captured["options"].mode == "lexical"
    assert result == [
        RetrievedChunk(
            id=17,
            external_id="guide.md#install",
            url="https://example.test/modelable/playground/guide/#install",
            score=4.5,
            title="Guide",
            heading="Install",
            content="Install with uv.",
            source_path="guide.md",
            heading_path=["Guide", "Install"],
            content_hash="hash-1",
        )
    ]


def test_browser_documentation_retriever_wraps_searchable_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingSearchClient:
        def __init__(self, index_url: str, **kwargs: object) -> None:
            self.index_url = index_url
            self.kwargs = kwargs

        def search(self, query: str, options: object) -> object:
            raise FileNotFoundError("missing manifest")

    monkeypatch.setattr(browser_rag, "SearchClient", FailingSearchClient)

    retriever = BrowserDocumentationRetriever(
        "docs-index/manifest.json",
        "https://example.test/modelable/playground/",
    )

    with pytest.raises(BrowserRetrievalError, match="missing manifest"):
        retriever.search("install docs")

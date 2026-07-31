from dataclasses import dataclass

import pytest

from modelable.llm.provider_types import LLMRequest, LLMResponse
from modelable.rag.generation import (
    answer_with_retrieval,
    build_evidence_prompt,
)
from modelable.rag.retriever import RetrievedChunk


def chunk(number: int, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=number,
        external_id=f"guide.md#section-{number}",
        url=f"https://example.test/guide/#section-{number}",
        score=10.0 - number,
        title="Guide",
        heading=f"Section {number}",
        content=content,
        source_path="guide.md",
        heading_path=["Guide", f"Section {number}"],
        content_hash=f"hash-{number}",
    )


@dataclass
class FakeRetriever:
    chunks: list[RetrievedChunk]
    query: str | None = None
    limit: int | None = None

    def search(self, query: str, *, limit: int = 8) -> list[RetrievedChunk]:
        self.query = query
        self.limit = limit
        return self.chunks


class FakeProvider:
    def __init__(self, content: str = "Use [S1] to configure the service.") -> None:
        self.content = content
        self.request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.request = request
        return LLMResponse(content=self.content, provider="fake", model="test")


def test_build_evidence_prompt_labels_sources_and_keeps_whole_chunks() -> None:
    first = chunk(1, "one two")
    second = chunk(2, "three four five")

    prompt, selected = build_evidence_prompt("How do I configure it?", [first, second], max_context_words=3)

    assert selected == (first,)
    assert "Question:\nHow do I configure it?" in prompt
    assert "[S1] Guide — Section 1" in prompt
    assert first.content in prompt
    assert second.content not in prompt
    assert first.url in prompt
    assert first.external_id in prompt


def test_context_budget_skips_oversized_chunk_and_keeps_later_fit() -> None:
    oversized = chunk(1, "one two three four")
    fitting = chunk(2, "five six")

    _, selected = build_evidence_prompt("question", [oversized, fitting], max_context_words=2)

    assert selected == (fitting,)


def test_answer_returns_insufficient_evidence_without_calling_provider() -> None:
    retriever = FakeRetriever([])
    provider = FakeProvider()

    result = answer_with_retrieval(retriever, provider, "unknown")

    assert result.insufficient_evidence is True
    assert result.citations == ()
    assert "enough documentation evidence" in result.answer
    assert provider.request is None


def test_answer_calls_provider_and_appends_structured_citations() -> None:
    retriever = FakeRetriever([chunk(1, "Configure the service with a token.")])
    provider = FakeProvider("Configure it with a token. [S1]")

    result = answer_with_retrieval(retriever, provider, "How do I configure it?", limit=3)

    assert retriever.query == "How do I configure it?"
    assert retriever.limit == 3
    assert provider.request is not None
    assert "[S1]" in provider.request.user
    assert result.insufficient_evidence is False
    assert result.citations[0].label == "S1"
    assert result.citations[0].external_id == "guide.md#section-1"
    assert "Sources:" in result.answer
    assert "https://example.test/guide/#section-1" in result.answer


def test_answer_applies_source_diversity_cap_before_prompt_and_citations() -> None:
    retriever = FakeRetriever([chunk(1, "first"), chunk(2, "second"), chunk(3, "third")])
    provider = FakeProvider()

    result = answer_with_retrieval(retriever, provider, "question", max_chunks_per_source=2)

    assert [citation.external_id for citation in result.citations] == [
        "guide.md#section-1",
        "guide.md#section-2",
    ]
    assert "guide.md#section-3" not in result.answer
    assert provider.request is not None
    assert "guide.md#section-3" not in provider.request.user


def test_answer_requires_provider_when_evidence_is_available() -> None:
    with pytest.raises(ValueError, match="LLM provider is required"):
        answer_with_retrieval(FakeRetriever([chunk(1, "evidence")]), None, "question")


@pytest.mark.parametrize("question", ["", "   "])
def test_answer_rejects_blank_question(question: str) -> None:
    with pytest.raises(ValueError, match="question must not be blank"):
        answer_with_retrieval(FakeRetriever([]), FakeProvider(), question)

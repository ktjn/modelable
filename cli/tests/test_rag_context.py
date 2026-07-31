from dataclasses import replace

import pytest

from modelable.rag.context import select_context
from modelable.rag.retriever import RetrievedChunk


def chunk(number: int, source: str, content: str, *, content_hash: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        id=number,
        external_id=f"{source}#section-{number}",
        url=f"https://example.test/{source}#section-{number}",
        score=10.0 - number,
        title="Guide",
        heading=f"Section {number}",
        content=content,
        source_path=source,
        heading_path=["Guide", f"Section {number}"],
        content_hash=content_hash,
    )


def test_select_context_deduplicates_external_ids_and_content_hashes() -> None:
    first = chunk(1, "guide.md", "first", content_hash="same")
    duplicate_id = replace(first, content="second", content_hash="other")
    duplicate_hash = chunk(2, "other.md", "third", content_hash="same")

    selected = select_context(
        [first, duplicate_id, duplicate_hash],
        max_context_words=10,
    )

    assert selected == (first,)


def test_select_context_caps_chunks_per_source_without_reordering() -> None:
    candidates = [
        chunk(1, "guide.md", "one"),
        chunk(2, "guide.md", "two"),
        chunk(3, "other.md", "three"),
        chunk(4, "guide.md", "four"),
    ]

    selected = select_context(candidates, max_context_words=10, max_chunks_per_source=2)

    assert selected == (candidates[0], candidates[1], candidates[2])


def test_select_context_only_admits_complete_chunks_within_budget() -> None:
    candidates = [
        chunk(1, "guide.md", "one two three four five"),
        chunk(2, "guide.md", "four five"),
    ]

    selected = select_context(candidates, max_context_words=4)

    assert selected == (candidates[1],)


@pytest.mark.parametrize("budget", [0, -1])
def test_select_context_rejects_non_positive_budget(budget: int) -> None:
    with pytest.raises(ValueError, match="max_context_words must be positive"):
        select_context([], max_context_words=budget)


def test_select_context_rejects_non_positive_source_cap() -> None:
    with pytest.raises(ValueError, match="max_chunks_per_source must be positive"):
        select_context([], max_context_words=10, max_chunks_per_source=0)

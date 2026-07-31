"""Deterministic selection of retrieved chunks for RAG context."""

from collections.abc import Sequence

from modelable.rag.retriever import RetrievedChunk


def select_context(
    chunks: Sequence[RetrievedChunk],
    *,
    max_context_words: int,
    max_chunks_per_source: int | None = None,
) -> tuple[RetrievedChunk, ...]:
    """Select complete, diverse evidence chunks in retrieval order."""
    if max_context_words <= 0:
        raise ValueError("max_context_words must be positive")
    if max_chunks_per_source is not None and max_chunks_per_source <= 0:
        raise ValueError("max_chunks_per_source must be positive")

    selected: list[RetrievedChunk] = []
    seen_external_ids: set[str] = set()
    seen_content_hashes: set[str] = set()
    source_counts: dict[str, int] = {}
    used_words = 0

    for chunk in chunks:
        if chunk.external_id in seen_external_ids:
            continue
        if chunk.content_hash and chunk.content_hash in seen_content_hashes:
            continue
        if max_chunks_per_source is not None and source_counts.get(chunk.source_path, 0) >= max_chunks_per_source:
            continue

        word_count = len(chunk.content.split())
        if used_words + word_count > max_context_words:
            continue

        selected.append(chunk)
        seen_external_ids.add(chunk.external_id)
        if chunk.content_hash:
            seen_content_hashes.add(chunk.content_hash)
        source_counts[chunk.source_path] = source_counts.get(chunk.source_path, 0) + 1
        used_words += word_count

    return tuple(selected)

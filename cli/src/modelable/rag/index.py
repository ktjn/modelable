from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from searchable_indexer.build_index import build_index_documents
from searchable_indexer.document import FieldDefinition, IndexDocument
from searchable_indexer.write_index import write_index

from modelable.rag.model import DocumentationChunk

FIELD_DEFINITIONS = {
    "title": FieldDefinition(indexed=True, stored=True, boost=3.0),
    "heading": FieldDefinition(indexed=True, stored=True, boost=2.0),
    "content": FieldDefinition(indexed=True, stored=True, boost=1.0),
    "source_path": FieldDefinition(indexed=False, stored=True),
}


@dataclass(slots=True, frozen=True)
class IndexBuildReport:
    source_document_count: int
    chunk_count: int
    languages: tuple[str, ...]
    output_directory: Path
    validation_errors: tuple[str, ...]


def to_index_document(chunk: DocumentationChunk, numeric_id: int) -> IndexDocument:
    if numeric_id <= 0:
        raise ValueError(f"numeric Searchable ID must be positive: {numeric_id}")
    return IndexDocument(
        id=numeric_id,
        external_id=chunk.external_id,
        url=chunk.url,
        language=chunk.language,
        indexed_fields={
            "title": chunk.title,
            "heading": chunk.heading or "",
            "content": chunk.content,
        },
        stored_fields={
            "title": chunk.title,
            "heading": chunk.heading or "",
            "content": chunk.content,
            "source_path": chunk.source_path,
        },
        metadata={
            "headingPath": list(chunk.heading_path),
            "chunkIndex": chunk.chunk_index,
        },
    )


def build_documentation_index(
    chunks: Sequence[DocumentationChunk],
    output_directory: Path,
    *,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
    embedding_provider: dict[str, object] | None = None,
    vector_quantization: str = "int8",
    term_shard_format: str = "json",
    doc_store_format: str = "json",
    fuzzy_shard_format: str = "json",
) -> IndexBuildReport:
    if embedding_provider is not None and embed is None:
        raise ValueError("embed is required when embedding_provider is supplied")

    ordered_chunks = sorted(chunks, key=lambda chunk: (chunk.source_path, chunk.chunk_index, chunk.external_id))
    seen_external_ids: set[str] = set()
    seen_positions: set[tuple[str, int]] = set()
    for chunk in ordered_chunks:
        if chunk.external_id in seen_external_ids:
            raise ValueError(f"duplicate documentation chunk external ID: {chunk.external_id}")
        if chunk.chunk_index < 0:
            raise ValueError(f"chunk index must not be negative: {chunk.external_id}")
        position = (chunk.source_path, chunk.chunk_index)
        if position in seen_positions:
            raise ValueError(f"duplicate documentation chunk position: {chunk.source_path}#{chunk.chunk_index}")
        seen_external_ids.add(chunk.external_id)
        seen_positions.add(position)

    documents = [to_index_document(chunk, index) for index, chunk in enumerate(ordered_chunks, start=1)]
    if embed is None:
        built = build_index_documents(documents, field_definitions=FIELD_DEFINITIONS)
    else:
        built = build_index_documents(
            documents,
            field_definitions=FIELD_DEFINITIONS,
            embed=embed,
            embedding_provider=embedding_provider,
            vector_field="content",
            vector_quantization=vector_quantization,
        )
    write_index(
        built,
        str(output_directory),
        term_shard_format=term_shard_format,
        doc_store_format=doc_store_format,
        fuzzy_shard_format=fuzzy_shard_format,
    )

    return IndexBuildReport(
        source_document_count=len({chunk.source_path for chunk in ordered_chunks}),
        chunk_count=len(ordered_chunks),
        languages=tuple(sorted({chunk.language for chunk in ordered_chunks})),
        output_directory=output_directory,
        validation_errors=(),
    )

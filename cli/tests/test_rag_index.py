import json

import pytest

from modelable.rag.index import build_documentation_index, to_index_document
from modelable.rag.model import DocumentationChunk


def test_to_index_document_stores_complete_chunk_and_metadata():
    chunk = DocumentationChunk(
        external_id="guide.md#install",
        source_path="guide.md",
        url="https://example.test/guide/#install",
        language="en",
        title="Guide",
        heading="Install",
        heading_path=["Guide", "Install"],
        content="Install with uv.",
        chunk_index=2,
    )

    document = to_index_document(chunk, 17)

    assert document.id == 17
    assert document.external_id == "guide.md#install"
    assert document.indexed_fields["content"] == "Install with uv."
    assert document.stored_fields["content"] == "Install with uv."
    assert document.metadata == {"headingPath": ["Guide", "Install"], "chunkIndex": 2}


def test_build_documentation_index_writes_json_searchable_documents(tmp_path):
    chunks = [
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
    ]

    report = build_documentation_index(chunks, tmp_path / "index")
    manifest = json.loads((tmp_path / "index" / "manifest.json").read_text(encoding="utf-8"))
    doc_file = tmp_path / "index" / manifest["shards"]["docs"][0]["file"]
    documents = json.loads(doc_file.read_text(encoding="utf-8"))

    assert report.source_document_count == 1
    assert report.chunk_count == 1
    assert report.languages == ("en",)
    assert report.validation_errors == ()
    assert documents["1"]["externalId"] == "guide.md#install"
    assert documents["1"]["fields"]["content"] == "Install with uv."


def test_build_documentation_index_assigns_ids_deterministically(tmp_path):
    chunks = [
        DocumentationChunk(
            external_id="z.md#z",
            source_path="z.md",
            url="z.md",
            language="en",
            title="Z",
            heading="Z",
            heading_path=["Z"],
            content="Z content.",
            chunk_index=0,
        ),
        DocumentationChunk(
            external_id="a.md#a",
            source_path="a.md",
            url="a.md",
            language="en",
            title="A",
            heading="A",
            heading_path=["A"],
            content="A content.",
            chunk_index=0,
        ),
    ]

    first = build_documentation_index(chunks, tmp_path / "first")
    second = build_documentation_index(list(reversed(chunks)), tmp_path / "second")

    assert first.chunk_count == second.chunk_count == 2
    first_manifest = json.loads((tmp_path / "first" / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((tmp_path / "second" / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["fields"] == second_manifest["fields"]

    first_docs = json.loads(
        (tmp_path / "first" / first_manifest["shards"]["docs"][0]["file"]).read_text(encoding="utf-8")
    )
    second_docs = json.loads(
        (tmp_path / "second" / second_manifest["shards"]["docs"][0]["file"]).read_text(encoding="utf-8")
    )
    assert first_docs == second_docs


def test_build_documentation_index_can_write_vector_shards_with_provider_metadata(tmp_path):
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

    build_documentation_index(
        [chunk],
        tmp_path / "vector-index",
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_provider={"type": "custom", "model": "test"},
    )

    manifest = json.loads((tmp_path / "vector-index" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["vectors"]["dims"] == 2
    assert manifest["vectors"]["embeddingProvider"] == {"type": "custom", "model": "test"}


def test_build_documentation_index_rejects_provider_without_embedder(tmp_path):
    with pytest.raises(ValueError, match="embed is required"):
        build_documentation_index(
            [],
            tmp_path / "vector-index",
            embedding_provider={"type": "custom", "model": "test"},
        )

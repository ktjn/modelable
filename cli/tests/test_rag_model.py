from modelable.rag.model import DocumentationChunk


def test_documentation_chunk_preserves_source_addressable_fields():
    chunk = DocumentationChunk(
        external_id="docs/configuration.md#database-connections",
        source_path="docs/configuration.md",
        url="https://ktjn.github.io/modelable/configuration/",
        language="en",
        title="Configuration",
        heading="Database connections",
        heading_path=["Configuration", "Database connections"],
        content="Configure the database URL.",
        chunk_index=0,
    )

    assert chunk.external_id.endswith("#database-connections")
    assert chunk.heading_path == ["Configuration", "Database connections"]
    assert chunk.content == "Configure the database URL."

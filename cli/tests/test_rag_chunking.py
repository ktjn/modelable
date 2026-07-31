from modelable.rag.chunking import chunk_markdown, load_documentation_chunks


def test_chunk_markdown_preserves_heading_path_and_stable_anchor():
    chunks = chunk_markdown(
        "# Configuration\n\nIntro.\n\n## Database connections\n\nUse DATABASE_URL.",
        source_path="docs/configuration.md",
        url="https://example.test/configuration/",
    )

    assert [chunk.external_id for chunk in chunks] == [
        "docs/configuration.md#configuration",
        "docs/configuration.md#database-connections",
    ]
    assert chunks[1].heading_path == ["Configuration", "Database connections"]
    assert "Use DATABASE_URL." in chunks[1].content


def test_duplicate_headings_get_deterministic_suffixes():
    chunks = chunk_markdown(
        "# Guide\n\n## Install\n\nFirst.\n\n## Install\n\nSecond.",
        source_path="guide.md",
        url="guide/",
    )

    assert [chunk.external_id for chunk in chunks] == [
        "guide.md#install",
        "guide.md#install-2",
    ]
    assert all(chunk.heading_path == ["Guide", "Install"] for chunk in chunks)


def test_chunker_never_splits_fenced_code_tables_or_lists():
    content = """# Examples

```python
def connect():
    return database.connect()
```

| setting | value |
| --- | --- |
| host | localhost |

- first item
- second item
"""
    chunks = chunk_markdown(content, source_path="examples.md", url="examples/")

    combined = "\n".join(chunk.content for chunk in chunks)
    assert "def connect():\n    return database.connect()" in combined
    assert "| setting | value |\n| --- | --- |\n| host | localhost |" in combined
    assert "- first item\n- second item" in combined


def test_oversized_prose_splits_at_sentence_boundaries():
    content = "# Guide\n\n" + " ".join(f"Sentence {index}." for index in range(80))

    chunks = chunk_markdown(content, source_path="guide.md", url="guide/", target_words=20, max_words=20)

    assert len(chunks) > 1
    assert all(chunk.content.rstrip().endswith(".") for chunk in chunks)
    assert all("Sentence" in chunk.content for chunk in chunks)


def test_discovery_order_is_path_sorted(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "z.md").write_text("# Z\n\nText.", encoding="utf-8")
    (tmp_path / "a.md").write_text("# A\n\nText.", encoding="utf-8")
    (tmp_path / "nested" / "b.md").write_text("# B\n\nText.", encoding="utf-8")

    chunks = load_documentation_chunks(tmp_path)

    assert [chunk.source_path for chunk in chunks] == ["a.md", "nested/b.md", "z.md"]


def test_empty_document_produces_no_chunks():
    assert chunk_markdown("\n# Empty\n\n", source_path="empty.md", url="empty/") == []

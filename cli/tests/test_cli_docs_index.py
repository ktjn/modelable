from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_docs_index_builds_searchable_index_and_reports_counts(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    (source / "guide.md").write_text("# Guide\n\nInstall with uv.", encoding="utf-8")
    output = tmp_path / "dist" / "search-index"

    result = CliRunner().invoke(
        cli,
        [
            "docs-index",
            str(source),
            "--out",
            str(output),
            "--base-url",
            "https://example.test/docs/",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Source documents: 1" in result.output
    assert "Chunks: 1" in result.output
    assert (output / "manifest.json").exists()


def test_docs_index_empty_source_writes_empty_index(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    output = tmp_path / "index"

    result = CliRunner().invoke(cli, ["docs-index", str(source), "--out", str(output)])

    assert result.exit_code == 0, result.output
    assert "Source documents: 0" in result.output
    assert "Chunks: 0" in result.output
    assert (output / "manifest.json").exists()


def test_docs_index_reports_invalid_utf8_with_source_path(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    invalid = source / "invalid.md"
    invalid.write_bytes(b"# Invalid\n\xff")

    result = CliRunner().invoke(cli, ["docs-index", str(source)])

    assert result.exit_code != 0
    assert "invalid UTF-8 Markdown input" in result.output
    assert str(invalid) in result.output


def test_docs_index_rejects_file_source(tmp_path):
    source = tmp_path / "not-a-directory.md"
    source.write_text("# Not a directory", encoding="utf-8")

    result = CliRunner().invoke(cli, ["docs-index", str(source)])

    assert result.exit_code != 0
    assert "File" in result.output or "directory" in result.output

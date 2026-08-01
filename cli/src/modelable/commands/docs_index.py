from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console
from modelable.rag.chunking import load_documentation_chunks
from modelable.rag.index import build_documentation_index


def register_docs_index_commands(cli_group: click.Group) -> None:
    cli_group.add_command(docs_index)


@click.command("docs-index")
@click.argument(
    "source",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=Path("./dist/search-index"),
    show_default=True,
    help="Directory for the generated Searchable index.",
)
@click.option(
    "--base-url",
    type=str,
    default=None,
    help="Base URL joined with each source-relative Markdown path.",
)
@click.option(
    "--binary",
    is_flag=True,
    help="Write binary Searchable term, document, and fuzzy shards.",
)
def docs_index(source: Path, out_dir: Path, base_url: str | None, binary: bool) -> None:
    """Build a lexical Searchable index from Markdown documentation at SOURCE."""
    try:
        chunks = load_documentation_chunks(source, base_url=base_url)
        report = build_documentation_index(
            chunks,
            out_dir,
            term_shard_format="binary" if binary else "json",
            doc_store_format="binary" if binary else "json",
            fuzzy_shard_format="binary" if binary else "json",
        )
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error

    console.print(f"Source documents: {report.source_document_count}")
    console.print(f"Chunks: {report.chunk_count}")
    console.print(f"Languages: {', '.join(report.languages) if report.languages else '(none)'}")
    console.print(f"Output: {report.output_directory}")
    for validation_error in report.validation_errors:
        console.print(f"[red]ERROR[/red] {validation_error}")

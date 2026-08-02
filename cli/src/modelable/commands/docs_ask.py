from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.llm.config import resolve_llm_config
from modelable.llm.providers import build_provider
from modelable.rag.bundled_index import bundled_documentation_index_path
from modelable.rag.generation import answer_with_retrieval
from modelable.rag.retriever import DocumentationRetriever


def register_docs_ask_commands(cli_group: click.Group) -> None:
    cli_group.add_command(docs_ask)


@click.command("docs-ask")
@click.argument("question")
@click.option(
    "--docs-index",
    "docs_index",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional documentation search index manifest; defaults to the bundled index.",
)
@click.option("--limit", type=click.IntRange(min=1), default=8, show_default=True)
@click.option(
    "--max-context-words",
    type=click.IntRange(min=1),
    default=3000,
    show_default=True,
    help="Maximum number of evidence words sent to the provider.",
)
@click.option("--provider", default=None, help="LLM provider name.")
@click.option("--model", default=None, help="Provider model name.")
@click.option("--base-url", default=None, help="Optional provider base URL.")
@click.option("--json", "as_json", is_flag=True, help="Print a machine-readable JSON answer.")
def docs_ask(
    question: str,
    docs_index: Path | None,
    limit: int,
    max_context_words: int,
    provider: str | None,
    model: str | None,
    base_url: str | None,
    as_json: bool,
) -> None:
    """Answer QUESTION using evidence retrieved from the documentation index."""
    try:
        index = docs_index if docs_index is not None else bundled_documentation_index_path()
        config = resolve_llm_config(
            flag_provider=provider,
            flag_model=model,
            flag_base_url=base_url,
        )
        llm_provider = build_provider(config.provider, model=config.model, base_url=config.base_url)
        result = answer_with_retrieval(
            DocumentationRetriever(index),
            llm_provider,
            question,
            limit=limit,
            max_context_words=max_context_words,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise click.ClickException(str(error)) from error

    if as_json:
        click.echo(json.dumps(asdict(result), sort_keys=True))
        return
    console.print(result.answer)
